"""Read-only, progressively available views of actual production checkpoints.

Only known plan files and completed normalized scene clips are exposed. Thumbnail
bytes are cached in memory: viewing a frozen run never changes its artifacts.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from functools import lru_cache
from io import BytesIO
import json
import re
from pathlib import Path
import subprocess
import time
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image

from renderers.ffmpeg import FFmpeg


_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_JSON_LIMIT = 8 * 1024 * 1024


def _directory(settings, job) -> Path:
    root = Path(settings.output_dir).resolve()
    path = root / job.id
    if not _ID.fullmatch(job.id) or path.is_symlink() or path.resolve().parent != root:
        raise HTTPException(404, "Production preview not found")
    return path.resolve()


def _file(directory: Path, *parts: str) -> Path | None:
    candidate = directory
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            return None
    try:
        resolved = candidate.resolve()
        return resolved if resolved.is_relative_to(directory) and resolved.is_file() else None
    except OSError:
        return None


def _read(directory: Path, name: str) -> dict:
    path = _file(directory, name)
    if path is None:
        return {}
    try:
        # A checkpoint may still be being published. Incomplete JSON is not a
        # failed task and will simply become available on the next poll.
        if path.stat().st_size > _JSON_LIMIT:
            return {}
        with path.open("rb") as stream:
            raw = stream.read(_JSON_LIMIT + 1)
        if len(raw) > _JSON_LIMIT:
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _text(value, limit=2000) -> str:
    return value[:limit].strip() if isinstance(value, str) else ""


def _items(value, limit=200) -> list[dict]:
    return [item for item in value[:limit] if isinstance(item, dict)] if isinstance(value, list) else []


def _plans(directory: Path, topic: str) -> dict:
    script = _read(directory, "narration_script.json")
    segments = {s.get("id"): s for s in _items(script.get("segments")) if isinstance(s.get("id"), str)}
    plan = {}
    for name in ("video_plan.json", "storyboard.json", "director_plan.json", "teaching_plan.json"):
        candidate = _read(directory, name)
        if _items(candidate.get("scenes")):
            plan = candidate
            break
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    title = _text(metadata.get("title"), 300) or _text(script.get("title"), 300) or topic
    rows, seen = [], set()
    for scene in _items(plan.get("scenes")):
        scene_id = scene.get("scene_id")
        if not isinstance(scene_id, str) or not _ID.fullmatch(scene_id) or scene_id in seen:
            continue
        seen.add(scene_id)
        segment = segments.get(scene.get("segment_id"), {}) if isinstance(scene.get("segment_id"), str) else {}
        rows.append({
            "id": scene_id, "index": len(rows) + 1,
            "title": _text(scene.get("title"), 300) or _text(segment.get("title"), 300) or f"分镜 {len(rows) + 1}",
            "narration": _text(scene.get("narration")) or _text(segment.get("narration")),
            "visual_description": (_text(scene.get("visual_concept")) or _text(scene.get("learning_goal"))
                                   or _text(segment.get("intent"))),
            "state": "planned", "image_url": None, "video_url": None,
        })
    excerpt = "\n".join(_text(s.get("narration")) for s in segments.values())
    if not excerpt:
        excerpt = "\n".join(row["narration"] for row in rows)
    return {"title": title or None, "script_excerpt": excerpt[:1600] or None, "scenes": rows}


def _completed(directory: Path, scene_id: str, clip: Path, telemetry: dict, report: dict) -> bool:
    stages = telemetry.get("stages") if isinstance(telemetry.get("stages"), dict) else {}
    raw_attempts = stages.get("animation")
    # Retain the latest attempts even on a long-lived, repeatedly resumed job.
    attempts = [entry for entry in _items(raw_attempts[-10000:] if isinstance(raw_attempts, list) else [], 10000)
                if entry.get("unit") == scene_id]
    if attempts:
        latest = attempts[-1]
        if latest.get("status") not in {"completed", "cached"} or not latest.get("completed_at"):
            return False
        try:
            # Do not publish a previous attempt while its clip is being replaced.
            return clip.stat().st_mtime <= datetime.fromisoformat(latest["completed_at"]).timestamp() + 1
        except (OSError, TypeError, ValueError):
            return False
    marker = _file(directory, "scenes", scene_id, "render.sha256")
    if marker:
        try:
            return (marker.stat().st_size == 64 and re.fullmatch(r"[0-9a-f]{64}", marker.read_text()) is not None
                    and marker.stat().st_mtime_ns >= clip.stat().st_mtime_ns)
        except (OSError, ValueError):
            return False
    return any(scene.get("scene_id") == scene_id for scene in _items(report.get("scenes")))


def _stamp(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


@lru_cache(maxsize=256)
def _duration(path: str, stamp: tuple[int, int], binary: str, probe: str | None) -> float | None:
    if stamp[0] < 32:
        return None
    try:
        if probe:
            process = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                                      "-of", "json", path], capture_output=True, timeout=4, check=True)
            data = json.loads(process.stdout)
            duration = float(data.get("format", {}).get("duration", 0))
            has_video = any(stream.get("codec_type") == "video" for stream in data.get("streams", []))
        else:
            process = subprocess.run([binary, "-hide_banner", "-nostdin", "-i", path, "-t", "0",
                                      "-f", "null", "-"], capture_output=True, timeout=4, check=True)
            output = process.stderr.decode("utf-8", errors="replace")
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
            duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3]) if match else 0
            has_video = "Video:" in output
        return duration if has_video and 0 < duration < 7200 else None
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None


def _ready_clip(directory: Path, scene_id: str, telemetry: dict, report: dict, ffmpeg) -> Path | None:
    clip = _file(directory, "scenes", scene_id, "normalized.mp4")
    if clip is None or not _completed(directory, scene_id, clip, telemetry, report):
        return None
    try:
        stamp = _stamp(clip)
        if _duration(str(clip), stamp, ffmpeg.binary, ffmpeg.probe_binary) is None or _stamp(clip) != stamp:
            return None
        return clip
    except OSError:
        return None


@lru_cache(maxsize=32)
def _image(path: str, stamp: tuple[int, int], binary: str, probe: str | None) -> bytes:
    duration = _duration(path, stamp, binary, probe)
    if duration is None:
        raise ValueError("Scene is not ready")
    process = subprocess.run([
        binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", str(min(2.0, duration / 4)),
        "-i", path, "-frames:v", "1", "-an", "-vf", "scale='min(960,iw)':-2",
        "-c:v", "mjpeg", "-q:v", "3", "-f", "image2pipe", "-",
    ], capture_output=True, timeout=20, check=True)
    image = process.stdout
    if not image or len(image) > 4 * 1024 * 1024:
        raise ValueError("Invalid scene image")
    with Image.open(BytesIO(image)) as decoded:
        if decoded.format != "JPEG" or decoded.width > 960 or min(decoded.size) < 1:
            raise ValueError("Invalid scene image")
        decoded.verify()
    if _stamp(Path(path)) != stamp:
        raise ValueError("Scene changed")
    return image


def _snapshot(settings, job):
    directory = _directory(settings, job)
    result = _plans(directory, job.topic)
    result["previews_pending"] = False
    telemetry, report = _read(directory, "telemetry_state.json"), _read(directory, "render_report.json")
    try:
        ffmpeg = FFmpeg(settings)
    except Exception:
        return result
    # First-time media probes share a small wall-clock budget. Subsequent polls
    # reuse cached probe results and progressively inspect the remaining clips,
    # instead of letting a large/corrupt batch hold the API for minutes.
    deadline = time.monotonic() + 2
    for scene in result["scenes"]:
        if time.monotonic() >= deadline:
            result["previews_pending"] = True
            break
        clip = _ready_clip(directory, scene["id"], telemetry, report, ffmpeg)
        if clip:
            try:
                size, modified = _stamp(clip)
            except OSError:
                continue
            revision = f"{modified}-{size}"
            base = f"/jobs/{quote(job.id, safe='')}/production/scenes/{quote(scene['id'], safe='')}"
            scene.update(state="ready", image_url=f"{base}/image?revision={revision}",
                         video_url=f"{base}/video?revision={revision}")
    return result


def register_production_routes(app, settings, protected, find_job, artifact_path):
    semaphore = asyncio.Semaphore(2)

    @app.get("/jobs/{job_id}/production", dependencies=protected)
    async def production(job_id: str, request: Request):
        job = find_job(request, job_id)
        async with semaphore:
            result = await asyncio.to_thread(_snapshot, settings, job)
        return Response(json.dumps(result, ensure_ascii=False), media_type="application/json",
                        headers={"Cache-Control": "no-store"})

    @app.get("/jobs/{job_id}/production/scenes/{scene_id}/{kind}", dependencies=protected)
    async def scene_media(job_id: str, scene_id: str, kind: str, request: Request):
        job = find_job(request, job_id)
        if not _ID.fullmatch(scene_id) or kind not in {"image", "video"}:
            raise HTTPException(404, "Scene preview not found")
        directory = _directory(settings, job)
        if scene_id not in {scene["id"] for scene in _plans(directory, job.topic)["scenes"]}:
            raise HTTPException(404, "Scene preview not found")
        try:
            ffmpeg = FFmpeg(settings)
            async with semaphore:
                clip = await asyncio.to_thread(_ready_clip, directory, scene_id, _read(directory, "telemetry_state.json"),
                                               _read(directory, "render_report.json"), ffmpeg)
                if clip is None:
                    raise HTTPException(409, "Scene is not ready")
                # Reuse the API's second independent confinement check.
                clip = artifact_path(job, str(clip))
                if kind == "video":
                    return FileResponse(clip, media_type="video/mp4", headers={"Cache-Control": "private, no-cache"})
                content = await asyncio.to_thread(_image, str(clip), _stamp(clip), ffmpeg.binary, ffmpeg.probe_binary)
                return Response(content, media_type="image/jpeg", headers={"Cache-Control": "private, no-cache"})
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Scene preview is temporarily unavailable") from None
