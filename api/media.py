"""Small cached previews derived from completed videos, never demo placeholders."""
from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from filelock import FileLock
from PIL import Image

from renderers.ffmpeg import FFmpeg


def _safe_child(directory: Path, name: str) -> Path:
    path = directory / name
    # Refuse cache/lock symlinks even if they point somewhere else in this job.
    if path.is_symlink() or path.resolve().parent != directory:
        raise HTTPException(404, "Thumbnail not found")
    return path


def _valid_jpeg(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            if image.format != "JPEG" or image.width > 960 or min(image.size) < 1:
                return False
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def _thumbnail(source: Path, directory: Path, settings) -> Path:
    target = _safe_child(directory, "preview.jpg")
    lock_path = _safe_child(directory, ".thumbnail.lock")
    with FileLock(lock_path, timeout=15):
        target = _safe_child(directory, "preview.jpg")
        if _valid_jpeg(target) and target.stat().st_mtime_ns >= source.stat().st_mtime_ns:
            return target

        ffmpeg = FFmpeg(settings)
        position = min(2.0, ffmpeg.duration(source) / 4)
        # A unique temporary file avoids publishing a partial JPEG, including
        # when the API or FFmpeg process is interrupted while generating it.
        with NamedTemporaryFile(prefix=".preview-", suffix=".jpg", dir=directory, delete=False) as file:
            temporary = Path(file.name)
        try:
            ffmpeg.run([
                "-ss", str(position), "-i", str(source), "-frames:v", "1", "-an",
                "-vf", "scale='min(960,iw)':-2", "-c:v", "mjpeg", "-q:v", "3",
                "-f", "image2", "-update", "1", str(temporary),
            ])
            if not _valid_jpeg(temporary):
                raise RuntimeError("No valid thumbnail was produced")
            _safe_child(directory, "preview.jpg")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


def register_media_routes(app, settings, protected, find_job, artifact_path) -> None:
    @app.get("/jobs/{job_id}/thumbnail", dependencies=protected)
    async def thumbnail(job_id: str, request: Request):
        job = find_job(request, job_id)
        if getattr(job.status, "value", job.status) != "succeeded" or not job.output_path:
            raise HTTPException(409, "Video is not ready")
        source = artifact_path(job, job.output_path)
        output_root = Path(settings.output_dir).resolve()
        directory = (output_root / job.id).resolve()
        if not directory.is_relative_to(output_root) or not source.is_relative_to(directory):
            raise HTTPException(404, "Thumbnail not found")
        try:
            image = await asyncio.to_thread(_thumbnail, source, directory, settings)
        except HTTPException:
            raise
        except Exception:
            # Renderer errors can contain process details; the public endpoint
            # needs only a retryable status and must not return those details.
            raise HTTPException(503, "Thumbnail is temporarily unavailable") from None
        return FileResponse(
            artifact_path(job, str(image)), media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=300"},
        )
