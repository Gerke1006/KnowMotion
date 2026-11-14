from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path

from renderers.base import RendererError, require_output, run_command, setting


class FFmpeg:
    def __init__(self, settings=None):
        self.narration_lufs = float(setting(settings, "narration_lufs", -16))
        configured = setting(settings, "ffmpeg_path")
        self.binary = str(configured) if configured else shutil.which("ffmpeg")
        if not self.binary:
            try:
                import imageio_ffmpeg

                self.binary = imageio_ffmpeg.get_ffmpeg_exe()
            except (ImportError, RuntimeError) as exc:
                raise RendererError(
                    "FFmpeg is required. Install ffmpeg or `pip install imageio-ffmpeg`."
                ) from exc
        self.probe_binary = setting(settings, "ffprobe_path") or shutil.which("ffprobe")

    def run(self, args: list[str]) -> str:
        return run_command([self.binary, "-hide_banner", "-nostdin", "-y", *map(str, args)])

    def duration(self, path: Path) -> float:
        if self.probe_binary:
            output = run_command(
                [
                    str(self.probe_binary),
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ]
            )
            try:
                duration = float(json.loads(output)["format"]["duration"])
            except (ValueError, KeyError) as exc:
                raise RendererError(f"Unable to probe duration of {path.name}") from exc
        else:
            # The bundled FFmpeg distribution has no ffprobe. Inspect its own input metadata.
            output = self.run(["-i", str(path), "-t", "0", "-f", "null", "-"])
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
            if not match:
                raise RendererError(f"Unable to inspect duration of {path.name}")
            duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        if duration <= 0:
            raise RendererError(f"Invalid media duration: {path.name}")
        return duration

    def normalize(
        self,
        source: Path,
        target: Path,
        metadata: dict,
        duration: float,
        voice: Path | None = None,
        effects: list[dict] | None = None,
        voice_offset: float = 0,
    ) -> Path:
        width, height, fps = (
            int(metadata.get("width", 1280)),
            int(metadata.get("height", 720)),
            int(metadata.get("fps", 24)),
        )
        args = ["-i", str(source)]
        if voice:
            args += ["-i", str(voice)]
        else:
            args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        effects = effects or []
        for effect in effects:
            effect_path = Path(effect["path"])
            if not effect_path.is_file():
                raise RendererError(f"Sound effect is missing: {effect_path.name}")
            args += ["-i", str(effect_path)]
        voice_processing = (
            f"loudnorm=I={getattr(self, 'narration_lufs', -16)}:TP=-1.5:LRA=11:dual_mono=true,"
            if voice else ""
        )
        filters = [
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},setsar=1,"
            f"tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration},setpts=PTS-STARTPTS[v]",
            f"[1:a]aresample=48000,{voice_processing}adelay={round(voice_offset * 1000)}:all=1,"
            f"apad,atrim=duration={duration},asetpts=PTS-STARTPTS[voice]",
        ]
        audio_labels = ["[voice]"]
        for i, effect in enumerate(effects, 2):
            delay = max(0, int(float(effect.get("at", 0)) * 1000))
            volume = min(2, max(0, float(effect.get("volume", 0.3))))
            filters.append(f"[{i}:a]aresample=48000,volume={volume},adelay={delay}|{delay}[fx{i}]")
            audio_labels.append(f"[fx{i}]")
        filters.append(
            "".join(audio_labels)
            + f"amix=inputs={len(audio_labels)}:duration=first:normalize=0,alimiter=limit=0.95[a]"
        )
        args += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(target),
        ]
        self.run(args)
        return require_output(target)

    def trim_narration(self, source: Path, output: Path) -> dict:
        """Remove only edge silence, preserving quiet consonants and internal pauses."""
        duration = self.duration(source)
        log = self.run(["-i", str(source), "-af", "silencedetect=noise=-55dB:d=0.06", "-f", "null", "-"])
        events = [(kind, float(value)) for kind, value in
                  re.findall(r"silence_(start|end):\s*([0-9.]+)", log)]
        start, end = 0.0, duration
        if events and events[0][0] == "start" and events[0][1] < .02:
            first_end = next((value for kind, value in events if kind == "end"), duration)
            start = max(0, first_end - .04)
        if events:
            last_start = next((value for kind, value in reversed(events) if kind == "start"), None)
            if last_start is not None and (events[-1][0] == "start" or events[-1][1] >= duration - .08):
                end = min(duration, last_start + .04)
        if end - start < .1:
            raise RendererError("Narration contains no usable speech")
        self.run(["-i", str(source), "-af", f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS",
                  "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(output)])
        require_output(output)
        return {"original_duration": duration, "trim_start": start, "trim_end": duration - end,
                "duration": self.duration(output)}

    def compose(self, clips: list[Path], output: Path, metadata: dict, durations: list[float],
                transition_duration: float = .30, speed: float = 1.15) -> dict:
        """Dissolve pictures while joining speech at the midpoint of silent handles.

        Audio is cut only within the handles, so voices neither overlap nor fade
        away at sentence boundaries. BGM is mixed once after retiming the result.
        """
        if not clips or len(clips) != len(durations):
            raise RendererError("Composition requires one positive duration per clip")
        if not .5 <= speed <= 2 or not 0 <= transition_duration <= 1 or any(d <= 0 for d in durations):
            raise RendererError("Invalid composition timing")
        fps = int(metadata.get("fps", 30))
        overlaps = [math.floor((min(transition_duration, a / 3, b / 3) + 1e-8) * fps) / fps
                    for a, b in zip(durations, durations[1:])]
        args, filters = [], []
        for index, (clip, duration) in enumerate(zip(clips, durations)):
            args += ["-i", str(clip)]
            filters.append(f"[{index}:v]fps={fps},settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v{index}]")
            head = overlaps[index - 1] / 2 if index else 0
            tail = overlaps[index] / 2 if index < len(overlaps) else 0
            filters.append(f"[{index}:a]atrim=start={head:.6f}:end={duration-tail:.6f},"
                           f"asetpts=PTS-STARTPTS[a{index}]")
        elapsed, current, transitions = durations[0], "v0", []
        for index, overlap in enumerate(overlaps, 1):
            offset = elapsed - overlap
            label = f"mix{index}"
            if overlap:
                filters.append(f"[{current}][v{index}]xfade=transition=fade:duration={overlap:.6f}:"
                               f"offset={offset:.6f}[{label}]")
            else:
                filters.append(f"[{current}][v{index}]concat=n=2:v=1:a=0,settb=AVTB[{label}]")
            transitions.append({"from_scene": index - 1, "to_scene": index,
                                "start": offset / speed, "end": elapsed / speed,
                                "duration": overlap / speed, "type": "dissolve" if overlap else "cut"})
            elapsed += durations[index] - overlap
            current = label
        final_duration = elapsed / speed
        filters.append(f"[{current}]setpts=(PTS-STARTPTS)/{speed},fps={fps}[video]")
        labels = "".join(f"[a{i}]" for i in range(len(clips)))
        filters.append(f"{labels}concat=n={len(clips)}:v=0:a=1,atempo={speed},apad,"
                       f"atrim=duration={final_duration:.6f}[audio]")
        self.run([*args, "-filter_complex_threads", "1", "-filter_complex", ";".join(filters),
                  "-map", "[video]", "-map", "[audio]", "-t", f"{final_duration:.6f}",
                  "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(output)])
        require_output(output)
        return {"playback_speed": speed, "source_duration": elapsed, "expected_duration": final_duration,
                "transition_duration": transition_duration, "transitions": transitions,
                "audio_join": "speech-preserving midpoint cuts in silent transition handles"}

    def concat(self, clips: list[Path], output: Path) -> Path:
        if not clips:
            raise RendererError("No scenes to concatenate")
        manifest = output.with_suffix(".concat.txt")
        # ffconcat quote syntax differs from shell quoting. No shell is used.
        lines = [
            "file '" + str(path.resolve()).replace("\\", "/").replace("'", "'\\''") + "'" for path in clips
        ]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.run(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(manifest),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        return require_output(output)

    def mix_music(self, video: Path, music: Path, output: Path, volume: float = 0.30) -> Path:
        if not music.is_file():
            raise RendererError(f"Configured BGM does not exist: {music}")
        duration = self.duration(video)
        fade_out = max(0, duration - 2)
        filters = (
            f"[1:a]aresample=48000,volume={min(1, max(0, volume))},"
            f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out}:d=2[bgm];"
            "[0:a][bgm]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=0[a]"
        )
        self.run(
            [
                "-i",
                str(video),
                "-stream_loop",
                "-1",
                "-i",
                str(music),
                "-filter_complex",
                filters,
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                str(duration),
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        return require_output(output)
