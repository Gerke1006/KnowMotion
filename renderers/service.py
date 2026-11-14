from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from concurrent.futures import ThreadPoolExecutor
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

    def __init__(self, settings=None):
        self.settings = settings

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
        tts_enabled = bool(setting(self.settings, "tts_enabled", False))
        if tts_enabled and not setting(self.settings, "minimax_api_key", ""):
            raise RendererError("MINIMAX_API_KEY is required when TTS is enabled.")
        bgm_path = setting(self.settings, "bgm_path", "")
        if bgm_path and not Path(bgm_path).is_file():
            raise RendererError(f"Configured BGM does not exist: {bgm_path}")
        ids = [scene_filename(scene) for scene in data["scenes"]]
        if len(ids) != len(set(ids)):
            raise RendererError("Duplicate scene IDs are not allowed")
        # Check optional render dependencies before requesting any paid narration.
        for scene in data["scenes"]:
            effects = scene.get("audio", {}).get("effects", [])
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
            planned_duration = float(scene["duration"])
            if tts_enabled and scene.get("narration", "").strip():
                raw_voice = MiniMaxTTS(self.settings).synthesize(scene["narration"], folder / "narration.mp3")
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
                        "voice": hashlib.sha256(voice.read_bytes()).hexdigest() if voice else None,
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
            if not cached:
                video = adapter.render(scene, data["metadata"], folder)
                effects = scene.get("audio", {}).get("effects", [])
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
                "cached": cached,
                "clip": str(clip),
            }

        concurrency = max(1, min(16, int(setting(self.settings, "render_concurrency", 2))))
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="vibe-render") as executor:
            reports = list(executor.map(render_scene, data["scenes"]))
        final = output_dir / "final.mp4"
        joined = output_dir / "joined.mp4"
        composition = ffmpeg.compose([Path(r["clip"]) for r in reports], joined, data["metadata"],
                                     [float(r["duration"]) for r in reports], transition, speed)
        # Scene-local durations remain in render time; composition describes the
        # overlapping final timeline after the single synchronized speed change.
        data["composition"] = composition
        data["metadata"]["duration"] = composition["expected_duration"]
        (output_dir / "effective_storyboard.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if bgm_path:
            volume = float(setting(self.settings, "bgm_volume", 0.30))
            ffmpeg.mix_music(joined, Path(bgm_path), final, volume)
        else:
            shutil.copyfile(joined, final)
        # Decode the final media once to catch corrupt streams, with no visual/AI review.
        ffmpeg.run(["-v", "error", "-i", str(final), "-f", "null", "-"])
        report = {
            "scenes": reports,
            "composition": composition,
            "duration": ffmpeg.duration(final),
            "bgm": str(bgm_path) if bgm_path else None,
            "bgm_volume": float(setting(self.settings, "bgm_volume", .30)) if bgm_path else 0,
            "output": str(final),
            "checks": {"nonempty": final.stat().st_size > 32, "media_duration_positive": True},
        }
        (output_dir / "render_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return require_output(final)
