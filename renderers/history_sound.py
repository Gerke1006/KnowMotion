"""Mix original SFX on the final film clock, preserving the configured BGM gain."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from .base import RendererError, require_output

RESOURCE_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RATE = 48000


def _number(value, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise RendererError(f"Invalid {label} in final audio timeline.") from None
    if not math.isfinite(result):
        raise RendererError(f"Invalid {label} in final audio timeline.")
    return result


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _levels(ffmpeg, path: Path, processing: str = "", *, loop: bool = False) -> dict:
    args = ["-stream_loop", "-1"] if loop else []
    log = ffmpeg.run([*args, "-i", str(path), "-vn", "-af", processing + "volumedetect", "-f", "null", "-"])
    result = {}
    for name in ("mean_volume", "max_volume"):
        match = re.search(rf"{name}:\s*(-?\d+(?:\.\d+)?|-inf)\s*dB", log)
        result[name.replace("volume", "dbfs")] = float(match[1]) if match and match[1] != "-inf" else None
    return result


def mix_timeline_audio(ffmpeg, joined, final, events, resources, bgm_path, bgm_volume, output_dir,
                       *, measure_levels=True) -> dict:
    """Events are final seconds after voice/video retiming; assets stay at 1x.

    Input video contains narration only. This function applies no atempo, tempo
    estimation, automatic BGM calibration, or ducking. Its source fingerprints
    and sample-quantized placement report make each audible cue reproducible.
    """
    joined, final, output_dir = Path(joined), Path(final), Path(output_dir)
    if joined.resolve() == final.resolve():
        raise RendererError("Final audio mix must not overwrite its input video.")
    require_output(joined)
    duration = _number(ffmpeg.duration(joined), "film duration")
    volume = _number(bgm_volume, "BGM gain")
    if duration <= 0 or not 0 <= volume <= 1:
        raise RendererError("Final audio duration or configured BGM gain is outside supported bounds.")
    if not isinstance(events, list) or len(events) > 1000:
        raise RendererError("Final audio timeline must be an event list of at most 1000 cues.")
    cards = {item["id"]: item for item in resources.get("sfx_assets", [])}
    args = ["-i", str(joined)]
    filters = ["[0:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[voice]"]
    labels, placements, ids = ["[voice]"], [], set()
    music = Path(bgm_path) if bgm_path else None
    music_report = {"enabled": bool(music), "configured_gain": volume, "ducking": False,
                    "tempo": 1, "automatic_gain_calibration": False}
    input_index = 1
    music_processing = ""
    if music:
        if not music.is_file():
            raise RendererError("Configured BGM does not exist.")
        args.extend(["-stream_loop", "-1", "-i", str(music)])
        fade_in, fade_out = min(1.0, duration / 4), min(2.0, duration / 4)
        music_processing = (f"aresample=48000,aformat=channel_layouts=stereo,"
                            f"volume={volume:.9f},afade=t=in:st=0:d={fade_in:.9f},"
                            f"afade=t=out:st={duration-fade_out:.9f}:d={fade_out:.9f},"
                            f"atrim=duration={duration:.9f},asetpts=PTS-STARTPTS")
        filters.append(f"[{input_index}:a]{music_processing}[bgm]")
        labels.append("[bgm]")
        music_report.update({"source": str(music.resolve()), "sha256": _fingerprint(music),
                             "source_duration": ffmpeg.duration(music), "loop_if_needed": True,
                             "playback_start": 0, "playback_end": duration,
                             "fade_in": fade_in, "fade_out": fade_out})
        input_index += 1
    for event in events:
        if not isinstance(event, dict):
            raise RendererError("Invalid sound cue in final audio timeline.")
        cue_id, asset_id = event.get("cue_id"), event.get("asset_id")
        if not isinstance(cue_id, str) or not cue_id or cue_id in ids or asset_id not in cards:
            raise RendererError("Sound cues require unique IDs and approved catalog assets.")
        ids.add(cue_id)
        card = cards[asset_id]
        path = (RESOURCE_ROOT / card["path"]).resolve()
        allowed_root = (RESOURCE_ROOT / "assets" / "audio" / "history").resolve()
        if not path.is_relative_to(allowed_root) or not path.is_file() or path.suffix.lower() != ".wav":
            raise RendererError("Sound cue asset must be a bundled History Pack WAV.")
        digest = _fingerprint(path)
        if digest != card.get("sha256"):
            raise RendererError("History sound asset does not match its catalog fingerprint.")
        at, adjustment = _number(event.get("at"), "cue time"), _number(event.get("gain_db", 0), "cue gain")
        alignment = event.get("align", "onset")
        if alignment not in {"onset", "peak"} or not 0 <= at <= duration or not -24 <= adjustment <= 12:
            raise RendererError("Sound cue time, alignment or gain is outside supported bounds.")
        asset_duration = _number(card["duration"], "asset duration")
        anchor = _number(card[alignment], "asset anchor")
        peak = _number(card["peak"], "asset peak")
        if not 0 <= anchor < asset_duration or not 0 <= peak < asset_duration:
            raise RendererError("Sound asset timing metadata is invalid.")
        gain_db = _number(card["default_gain_db"], "catalog gain") + adjustment
        gain = 10 ** (gain_db / 20)
        raw_start = at - anchor
        trim_samples = max(0, round(-raw_start * SAMPLE_RATE))
        delay_samples = max(0, round(raw_start * SAMPLE_RATE))
        trim, playback_start = trim_samples / SAMPLE_RATE, delay_samples / SAMPLE_RATE
        playback_end = min(duration, playback_start + asset_duration - trim)
        args.extend(["-i", str(path)])
        label = f"fx{input_index}"
        filters.append(f"[{input_index}:a]aresample=48000,aformat=channel_layouts=stereo,"
                       f"atrim=start_sample={trim_samples},asetpts=PTS-STARTPTS,volume={gain:.9f},"
                       f"adelay={delay_samples}S:all=1[{label}]")
        labels.append(f"[{label}]")
        placements.append({"cue_id": cue_id, "asset_id": asset_id, "source": card["path"],
                           "sha256": digest, "source_duration": asset_duration, "trigger": at,
                           "align": alignment, "source_anchor": anchor, "source_peak": peak,
                           "playback_start": playback_start, "playback_end": playback_end,
                           "trim_start": trim, "delay_samples": delay_samples,
                           "trim_samples": trim_samples, "aligned_at": playback_start + anchor - trim,
                           "alignment_error_seconds": playback_start + anchor - trim - at,
                           "peak_at": playback_start + peak - trim,
                           "peak_in_film": 0 <= playback_start + peak - trim <= duration,
                           "default_gain_db": card["default_gain_db"], "adjustment_gain_db": adjustment,
                           "gain_db": gain_db, "gain": gain, "tempo": 1})
        input_index += 1
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,"
                   f"alimiter=limit=0.89:level=0:latency=1,atrim=duration={duration:.9f}[mixed]")
    output_dir.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    graph = ";".join(filters)
    ffmpeg.run([*args, "-filter_complex", graph, "-map", "0:v", "-map", "[mixed]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-t", f"{duration:.9f}", "-movflags", "+faststart", str(final)])
    require_output(final)
    report = {"schema_version": "1.0", "clock": "final-film-seconds", "duration": duration,
              "input_sha256": _fingerprint(joined), "output_sha256": _fingerprint(final),
              "output": str(final.resolve()), "sample_rate": SAMPLE_RATE,
              "playback_speed_applied_here": False, "limiter": {"limit": .89, "auto_level": False,
                                                                  "latency_compensated": True},
              "events": placements, "event_count": len(placements),
              "triggers_per_minute": len(placements) / duration * 60,
              "bgm": music_report, "filter_sha256": hashlib.sha256(graph.encode()).hexdigest(),
              "levels": ({"narration_input": _levels(ffmpeg, joined), "final_mix": _levels(ffmpeg, final)}
                         if measure_levels else {}),
              "levels_measured": measure_levels,
              "measurement_note": ("Full-track RMS/peak are diagnostic only; configured BGM gain is unchanged."
                                   if measure_levels else "Skipped for user-requested direct generation.")}
    if music and measure_levels:
        report["levels"]["bgm_at_configured_gain"] = _levels(ffmpeg, music, music_processing + ",", loop=True)
    (output_dir / "audio_mix_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    return report


def mix_history_audio(ffmpeg, joined, final, events, resources, bgm_path, bgm_volume, output_dir,
                      *, measure_levels=True) -> dict:
    """Compatible History Pack entry point for the shared final-clock mixer."""
    return mix_timeline_audio(ffmpeg, joined, final, events, resources, bgm_path, bgm_volume,
                              output_dir, measure_levels=measure_levels)
