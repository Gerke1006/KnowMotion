"""Isolated thumbnail endpoint regressions, not live video acceptance."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import time

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.main import create_app
from harness.schemas import JobCreate
from harness.settings import Settings
from storage.repository import JobRepository


@pytest.fixture
def media_service(tmp_path):
    settings = Settings(_env_file=None, project_root=tmp_path,
                        output_dir=tmp_path / "outputs", database_url="sqlite:///:memory:",
                        api_token="thumbnail-fixture-token")
    repository = JobRepository(settings.database_url)
    app = create_app(settings, repository=repository)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer thumbnail-fixture-token"
        yield client, repository, settings
    repository.close()


def completed_job(repository, settings):
    job = repository.create(JobCreate(topic="thumbnail fixture", mode="live"))
    folder = settings.output_dir / job.id
    folder.mkdir(parents=True)
    video = folder / "final.mp4"
    video.write_bytes(b"isolated-video-fixture")
    return repository.update(job.id, status="succeeded", stage="complete", progress=1,
                             output_path=str(video)), folder


def fake_encoder(monkeypatch, *, duration=12, delay=0, fail=False):
    calls = []
    lock = Lock()

    class Encoder:
        def __init__(self, _):
            pass

        def duration(self, _):
            return duration

        def run(self, args):
            with lock:
                calls.append(args)
            if delay:
                time.sleep(delay)
            if fail:
                raise RuntimeError("Internal encoder information must remain private")
            Image.new("RGB", (960, 540), "navy").save(Path(args[-1]), format="JPEG")

    monkeypatch.setattr("api.media.FFmpeg", Encoder)
    return calls


def test_thumbnail_requires_auth_and_completed_video(media_service, monkeypatch):
    client, repository, settings = media_service
    calls = fake_encoder(monkeypatch)
    job = repository.create(JobCreate(topic="pending", mode="live"))
    endpoint = f"/jobs/{job.id}/thumbnail"
    assert client.get(endpoint, headers={"Authorization": ""}).status_code == 401
    assert client.get(endpoint).status_code == 409
    assert client.get("/jobs/missing/thumbnail").status_code == 404
    assert calls == []


def test_thumbnail_is_real_jpeg_cached_and_bounded_for_short_video(media_service, monkeypatch):
    client, repository, settings = media_service
    calls = fake_encoder(monkeypatch, duration=1)
    job, folder = completed_job(repository, settings)
    endpoint = f"/jobs/{job.id}/thumbnail"
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == (folder / "preview.jpg").read_bytes()
    assert len(calls) == 1
    assert float(calls[0][calls[0].index("-ss") + 1]) < 1
    assert "min(960,iw)" in calls[0][calls[0].index("-vf") + 1]
    assert client.get(endpoint).content == response.content
    assert len(calls) == 1
    assert not list(folder.glob(".preview-*.jpg"))
    assert repository.get(job.id).artifacts == {}


def test_concurrent_thumbnail_requests_encode_once(media_service, monkeypatch):
    client, repository, settings = media_service
    calls = fake_encoder(monkeypatch, delay=.05)
    job, _ = completed_job(repository, settings)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: client.get(f"/jobs/{job.id}/thumbnail"), range(3)))
    assert all(response.status_code == 200 for response in results)
    assert len(calls) == 1


def test_thumbnail_rejects_source_escape_and_cache_symlink(media_service, monkeypatch, tmp_path):
    client, repository, settings = media_service
    calls = fake_encoder(monkeypatch)
    job, folder = completed_job(repository, settings)
    outside = tmp_path / "private.jpg"
    outside.write_bytes(b"private-file")
    repository.update(job.id, output_path=str(outside))
    assert client.get(f"/jobs/{job.id}/thumbnail").status_code == 404
    repository.update(job.id, output_path=str(folder / "final.mp4"))
    try:
        (folder / "preview.jpg").symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit symbolic links")
    assert client.get(f"/jobs/{job.id}/thumbnail").status_code == 404
    assert outside.read_bytes() == b"private-file"
    assert calls == []


def test_encoder_failure_returns_generic_retryable_error(media_service, monkeypatch):
    client, repository, settings = media_service
    fake_encoder(monkeypatch, fail=True)
    job, folder = completed_job(repository, settings)
    response = client.get(f"/jobs/{job.id}/thumbnail")
    assert response.status_code == 503
    assert response.json()["detail"] == "Thumbnail is temporarily unavailable"
    assert "Internal encoder" not in response.text
    assert not (folder / "preview.jpg").exists()
    assert not list(folder.glob(".preview-*.jpg"))
