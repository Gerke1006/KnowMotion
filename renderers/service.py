from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from .audio import MiniMaxTTS
from .base import RendererError, as_dict, require_output, scene_filename, setting
from .blender import BlenderRenderer
from .canvas import CanvasRenderer
from .ffmpeg import FFmpeg
from .manim import ManimRenderer
from .remotion import RemotionRenderer


class VideoRenderer:
    """Sync render facade; callers may run it with asyncio.to_thread.

    All model fields are data passed to trusted component templates. The service
    checks technical execution only; it performs no AI scoring or revision loop.
    """

    def __init__(self, settings=None, telemetry=None):
        self.settings = settings
        self.telemetry = telemetry

    @contextmanager
    def timed(self, stage, unit, *, cached=False):
        if self.telemetry:
            self.telemetry("start", stage, unit=unit, cached=cached)
        try:
            yield
        except BaseException:
            if self.telemetry:
                self.telemetry("fail", stage, unit=unit, cached=cached)
            raise
        else:
            if self.telemetry:
                self.telemetry("end", stage, unit=unit, cached=cached)

    def adapter(self, name: str):
        adapters = {
            "manim": ManimRenderer,
            "canvas": CanvasRenderer,
            "svg": CanvasRenderer,
            "remotion": RemotionRenderer,
            "blender": BlenderRenderer,
        }
        if name not in adapters:
            raise RendererError(f"Unsupported renderer: {name}")
        return adapters[name](self.settings)

    def generate(self, plan, output_dir: Path) -> list[Path]:
        data = as_dict(plan)
        output_dir = Path(output_dir)
        return [
            self.adapter(scene.get("renderer", "manim")).generate(
                scene, data["metadata"], output_dir / "scenes" / scene_filename(scene)
            )
            for scene in data["scenes"]
        ]

    def render(self, plan, output_dir: Path) -> Path:
        data = copy.deepcopy(as_dict(plan))
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg = FFmpeg(self.settings)
        fps = int(data["metadata"].get("fps", 30))
        transition = math.floor(float(setting(self.settings, "transition_duration", .30)) * fps + 1e-8) / fps
        speed = float(setting(self.settings, "playback_speed", 1.15))
        validation_enabled = bool(setting(self.settings, "video_validation_enabled", True))
        tts_enabled = bool(setting(self.settings, "tts_enabled", False))
        if tts_enabled and not setting(self.settings, "minimax_api_key", ""):
            raise RendererError("MINIMAX_API_KEY is required when TTS is enabled.")
        bgm_path = setting(self.settings, "bgm_path", "")
        if bgm_path and not Path(bgm_path).is_file():
            raise RendererError(f"Configured BGM does not exist: {bgm_path}")
        ids = [scene_filename(scene) for scene in data["scenes"]]
        if len(ids) != len(set(ids)):
            raise RendererError("Duplicate scene IDs are not allowed")
        has_math_timeline = any(scene.get("extensions", {}).get("math_animation_version") == "1.0"
                                for scene in data["scenes"])
        resources = None
        if has_math_timeline:
            if not tts_enabled or float(setting(self.settings, "tts_speed", 1)) != 1:
                raise RendererError("Word-aligned mathematics requires enabled MiniMax with TTS_SPEED=1.")
            resource_path = Path(setting(self.settings, "project_root", Path(__file__).resolve().parents[1])) / "assets/history/animation_resources.json"
            resources = json.loads(resource_path.read_text(encoding="utf-8"))
        # Check optional render dependencies before requesting any paid narration.
        if any(scene.get("renderer") == "remotion" for scene in data["scenes"]):
            RemotionRenderer(self.settings).preflight(ensure_browser=True)
        for scene in data["scenes"]:
            effects = scene.get("audio", {}).get("effects", [])
            if scene.get("extensions", {}).get("math_animation_version") == "1.0" and effects:
                raise RendererError("Math animation sound effects must use emphasis.sfx_id, not file paths.")
            asset_root = (
                Path(setting(self.settings, "project_root", Path(__file__).resolve().parents[1]))
                / "assets"
                / "audio"
            ).resolve()
            for effect in effects:
                candidate = Path(str(effect.get("path", "")))
                candidate = (
                    (asset_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
                )
                if not candidate.is_relative_to(asset_root) or not candidate.is_file():
                    raise RendererError("Sound effects must reference existing files within assets/audio.")
                effect["path"] = str(candidate)
            renderer = scene.get("renderer", "manim")
            if renderer == "manim" and not ManimRenderer(self.settings).available():
                if setting(self.settings, "renderer_fallback", False):
                    scene["renderer"] = "canvas"
                else:
                    raise RendererError(
                        "Manim is unavailable. Install [manim], select canvas, or enable RENDERER_FALLBACK."
                    )

        def render_scene(scene):
            name = scene_filename(scene)
            folder = output_dir / "scenes" / name
            folder.mkdir(parents=True, exist_ok=True)
            voice = None
            speech = None
            voice_offset = 0.0
            aligned = None
            word_aligned = scene.get("extensions", {}).get("math_animation_version") == "1.0"
            planned_duration = float(scene["duration"])
            if tts_enabled and scene.get("narration", "").strip():
                with self.timed("narration", name):
                    tts = MiniMaxTTS(self.settings)
                    if word_aligned:
                        aligned = tts.synthesize_aligned(scene["narration"], folder / "narration.mp3")
                        raw_voice = Path(aligned["audio_path"])
                    else:
                        raw_voice = tts.synthesize(scene["narration"], folder / "narration.mp3")
                    voice = folder / "narration.trimmed.wav"
                    speech = ffmpeg.trim_narration(raw_voice, voice)
                voice_offset = transition / 2
                audio = scene.setdefault("audio", {})
                audio["narration_duration"] = speech["duration"]
                audio["narration_offset"] = voice_offset
                # Fit the entire scene to speech, rather than padding a short voice
                # to a long planning estimate. Handles are consumed by transitions.
                scene["duration"] = speech["duration"] + transition + float(setting(self.settings, "narration_gap", .08))
            scene["duration"] = math.ceil(float(scene["duration"]) * fps - 1e-8) / fps
            if word_aligned:
                if aligned is None or speech is None:
                    raise RendererError("A mathematical animation requires real speech and word timestamps.")
                from harness.math_animation import compile_math_scene
                scene = compile_math_scene(scene, aligned["words"], speech, fps=fps, narration_offset=voice_offset)
                (folder / "math_timeline.json").write_text(
                    json.dumps(scene["extensions"]["math_timeline"], ensure_ascii=False, indent=2), encoding="utf-8")
            adapter = self.adapter(scene.get("renderer", "manim"))
            implementation = hashlib.sha256(
                b"".join(p.read_bytes() for p in sorted(Path(__file__).parent.rglob("*.py")))
            ).hexdigest()
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "scene": scene,
                        "metadata": data["metadata"],
                        "version": implementation,
                        "adapter_version": adapter.fingerprint() if hasattr(adapter, "fingerprint") else None,
                        "voice": hashlib.sha256(voice.read_bytes()).hexdigest() if voice else None,
                        "alignment": hashlib.sha256(Path(aligned["alignment_path"]).read_bytes()).hexdigest() if aligned else None,
                        "math_compiler": hashlib.sha256((Path(__file__).resolve().parents[1] / "harness/math_animation.py").read_bytes()).hexdigest()
                            if word_aligned else None,
                        "sound_resources": resources if word_aligned else None,
                        "narration_lufs": setting(self.settings, "narration_lufs", -16),
                        "font": setting(self.settings, "font_path", ""),
                        "manim_font": setting(self.settings, "manim_font", ""),
                        "typography": {key: setting(self.settings, key, "") for key in (
                            "chinese_font", "english_font", "subtitle_font", "subtitle_font_weight",
                            "subtitle_color", "subtitle_outline_color", "subtitle_outline_width",
                            "english_font_path", "subtitle_font_path", "latex_compiler_path",
                        )},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            clip = folder / "normalized.mp4"
            marker = folder / "render.sha256"
            cached = (
                clip.is_file()
                and clip.stat().st_size > 32
                and marker.is_file()
                and marker.read_text() == fingerprint
            )
            with self.timed("animation", name, cached=cached):
                if not cached:
                    video = adapter.render(scene, data["metadata"], folder)
                    effects = [] if word_aligned else scene.get("audio", {}).get("effects", [])
                    ffmpeg.normalize(video, clip, data["metadata"], float(scene["duration"]), voice, effects,
                                     voice_offset=voice_offset)
                    marker.write_text(fingerprint)
            return {
                "scene_id": name,
                "renderer": scene.get("renderer", "manim"),
                "duration": scene["duration"],
                "planned_duration": planned_duration,
                "speech": speech,
                "narration_offset": voice_offset,
                "narration": "minimax" if voice else "disabled",
                "voice_id": setting(self.settings, "minimax_voice_id", "") if voice else None,
                "voice_file": str(voice) if voice else None,
                "alignment_file": str(aligned["alignment_path"]) if aligned else None,
                "sound_events": scene.get("extensions", {}).get("math_timeline", {}).get("sfx", []),
                "cached": cached,
                "clip": str(clip),
                "resolved_scene": scene,
            }

        concurrency = max(1, min(16, int(setting(self.settings, "render_concurrency", 4))))
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="vibe-render") as executor:
            reports = list(executor.map(render_scene, data["scenes"]))
        data["scenes"] = [report.pop("resolved_scene") for report in reports]
        final = output_dir / "final.mp4"
        joined = output_dir / "joined.mp4"
        with self.timed("composition", "film"):
            composition = ffmpeg.compose([Path(r["clip"]) for r in reports], joined, data["metadata"],
                                         [float(r["duration"]) for r in reports], transition, speed)
            if has_math_timeline:
                from .history_sound import mix_timeline_audio
                events = [
                    {**event, "cue_id": f'{scene["scene_id"]}:{index}', "at": (base + event["at"]) / speed}
                    for scene, base in zip(reports, composition["scene_starts"])
                    for index, event in enumerate(scene["sound_events"])
                ]
                sound_report = mix_timeline_audio(ffmpeg, joined, final, events, resources, bgm_path,
                                                  float(setting(self.settings, "bgm_volume", .30)), output_dir,
                                                  measure_levels=validation_enabled)
                (output_dir / "sound_execution.json").write_text(
                    json.dumps(sound_report, ensure_ascii=False, indent=2), encoding="utf-8")
            elif bgm_path:
                volume = float(setting(self.settings, "bgm_volume", 0.30))
                ffmpeg.mix_music(joined, Path(bgm_path), final, volume)
            else:
                shutil.copyfile(joined, final)
        # Scene-local durations remain in render time; composition describes the
        # overlapping final timeline after the single synchronized speed change.
        data["composition"] = composition
        data["metadata"]["duration"] = composition["expected_duration"]
        (output_dir / "effective_storyboard.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Decode the final media once to catch corrupt streams, with no visual/AI review.
        if validation_enabled:
            ffmpeg.run(["-v", "error", "-i", str(final), "-f", "null", "-"])
        report = {
            "scenes": reports,
            "composition": composition,
            "duration": ffmpeg.duration(final),
            "bgm": str(bgm_path) if bgm_path else None,
            "bgm_volume": float(setting(self.settings, "bgm_volume", .30)) if bgm_path else 0,
            "output": str(final),
            "validation_performed": validation_enabled,
            "checks": {"nonempty": final.stat().st_size > 32, "media_duration_positive": True} if validation_enabled else {},
        }
        (output_dir / "render_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return require_output(final)
