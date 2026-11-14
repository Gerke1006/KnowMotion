"""Isolated preview API tests; these do not constitute video acceptance."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from api.main import create_app
from api import production
from harness.schemas import JobCreate
from harness.settings import Settings
from renderers.ffmpeg import FFmpeg
from storage.repository import JobRepository


@contextmanager
def preview_client(tmp_path, **options):
    settings = Settings(_env_file=None, project_root=tmp_path, output_dir=tmp_path / "outputs",
                        database_url="sqlite:///:memory:", **options)
    repository = JobRepository(settings.database_url)
    app = create_app(settings, repository=repository)
    with TestClient(app) as client:
        # Create directly after startup, never enqueue a model/render task.
        job = repository.create(JobCreate(topic="隔离的预览接口测试"))
        repository.update(job.id, status="running", stage="teaching")
        directory = settings.output_dir / job.id
        directory.mkdir(parents=True)
        yield client, job.id, directory, settings
    repository.close()


def save(directory, name, data):
    (directory / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def scene(scene_id="scene_01"):
    return {"scene_id": scene_id, "title": "认识变化率", "narration": "这是隔离测试中的讲稿。",
            "visual_concept": "观察曲线上的切线"}


@pytest.fixture
def clip_bytes(tmp_path):
    # A tiny local fixture, unrelated to real jobs or full Agent acceptance.
    settings = Settings(_env_file=None, project_root=tmp_path)
    binary = FFmpeg(settings).binary
    target = tmp_path / "isolated-fixture.mp4"
    subprocess.run([binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi",
                    "-i", "color=c=teal:s=160x90:r=10:d=0.4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(target)], capture_output=True, check=True, timeout=20)
    return target.read_bytes()


def test_plans_appear_only_after_actual_complete_checkpoints(tmp_path):
    with preview_client(tmp_path) as (client, job_id, directory, _):
        endpoint = f"/jobs/{job_id}/production"
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["scenes"] == []
        assert response.json()["script_excerpt"] is None
        assert response.json()["previews_pending"] is False
        (directory / "teaching_plan.json").write_text('{"scenes": [', encoding="utf-8")
        assert client.get(endpoint).json()["scenes"] == []
        save(directory, "teaching_plan.json", {"scenes": [scene()]})
        first = client.get(endpoint).json()["scenes"][0]
        assert first == {"id": "scene_01", "index": 1, "title": "认识变化率", "narration": "这是隔离测试中的讲稿。",
                         "visual_description": "观察曲线上的切线", "state": "planned", "image_url": None, "video_url": None}
        save(directory, "video_plan.json", {"metadata": {"title": "导数"}, "scenes": [scene(), scene("scene_02")]})
        result = client.get(endpoint).json()
        assert result["title"] == "导数"
        assert len(result["scenes"]) == 2
        # An interrupted publication uses the preceding intact checkpoint.
        (directory / "video_plan.json").write_text('{"scenes": [', encoding="utf-8")
        assert len(client.get(endpoint).json()["scenes"]) == 1


def test_history_script_precedes_director_and_resolved_scenes(tmp_path):
    with preview_client(tmp_path) as (client, job_id, directory, _):
        endpoint = f"/jobs/{job_id}/production"
        save(directory, "narration_script.json", {"title": "丝绸之路", "segments": [
            {"id": "seg1", "narration": "张骞出发前往西域。", "intent": "解释出使目的"}]})
        result = client.get(endpoint).json()
        assert result["script_excerpt"] == "张骞出发前往西域。"
        assert result["scenes"] == []
        save(directory, "director_plan.json", {"scenes": [{"scene_id": "scene_seg1", "segment_id": "seg1"}]})
        row = client.get(endpoint).json()["scenes"][0]
        assert row["narration"] == "张骞出发前往西域。"
        assert row["visual_description"] == "解释出使目的"
        assert row["state"] == "planned"
        save(directory, "video_plan.json", {"scenes": [{"scene_id": "scene_seg1", "segment_id": "seg1",
                                                        "title": "出使西域", "narration": "张骞出发前往西域。"}]})
        assert client.get(endpoint).json()["scenes"][0]["title"] == "出使西域"


def test_completed_scene_is_viewable_before_job_finishes_without_writing_artifacts(tmp_path, clip_bytes):
    with preview_client(tmp_path) as (client, job_id, directory, _):
        save(directory, "video_plan.json", {"scenes": [scene(), scene("scene_02")]})
        folder = directory / "scenes" / "scene_01"
        folder.mkdir(parents=True)
        (folder / "normalized.mp4").write_bytes(clip_bytes)
        save(directory, "telemetry_state.json", {"stages": {"animation": [
            {"unit": "scene_01", "status": "running", "completed_at": None}]}})
        endpoint = f"/jobs/{job_id}/production"
        assert client.get(endpoint).json()["scenes"][0]["state"] == "planned"
        assert client.get(f"{endpoint}/scenes/scene_01/video").status_code == 409
        save(directory, "telemetry_state.json", {"stages": {"animation": [
            {"unit": "scene_01", "status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}]}})
        snapshot = client.get(endpoint).json()
        assert snapshot["previews_pending"] is False
        assert snapshot["scenes"][0]["state"] == "ready"
        assert snapshot["scenes"][1]["state"] == "planned"
        before = {p.relative_to(directory): (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.rglob("*") if p.is_file()}
        url = snapshot["scenes"][0]["video_url"]
        assert client.get(url).content == clip_bytes
        assert client.get(url, headers={"Range": "bytes=0-3"}).status_code == 206
        image = client.get(snapshot["scenes"][0]["image_url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"
        assert image.content.startswith(b"\xff\xd8")
        after = {p.relative_to(directory): (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.rglob("*") if p.is_file()}
        assert before == after
        assert client.get(endpoint).json()["scenes"][0]["video_url"] == url
        # Replacing the same scene changes both URLs without changing its ID.
        clip = folder / "normalized.mp4"
        stat = clip.stat()
        os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        changed = client.get(endpoint).json()["scenes"][0]
        assert changed["video_url"] != url
        assert changed["image_url"] != snapshot["scenes"][0]["image_url"]
        assert "?revision=" in changed["video_url"]
        # A fresh running attempt suppresses the prior clip immediately.
        save(directory, "telemetry_state.json", {"stages": {"animation": [
            {"unit": "scene_01", "status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()},
            {"unit": "scene_01", "status": "running", "completed_at": None}]}})
        assert client.get(endpoint).json()["scenes"][0]["state"] == "planned"


def test_incomplete_corrupt_and_unlisted_media_are_never_published(tmp_path, clip_bytes):
    with preview_client(tmp_path) as (client, job_id, directory, _):
        save(directory, "video_plan.json", {"scenes": [scene()]})
        folder = directory / "scenes" / "scene_01"
        folder.mkdir(parents=True)
        (folder / "normalized.mp4").write_bytes(b"partial-not-an-mp4" * 10)
        (folder / "render.sha256").write_text("a" * 64)
        endpoint = f"/jobs/{job_id}/production"
        assert client.get(endpoint).json()["scenes"][0]["state"] == "planned"
        assert client.get(f"{endpoint}/scenes/scene_01/image").status_code == 409
        assert client.get(f"{endpoint}/scenes/not-listed/video").status_code == 404
        assert client.get(f"{endpoint}/scenes/scene_01/source").status_code == 404
        (folder / "normalized.mp4").write_bytes(clip_bytes)
        (folder / "render.sha256").write_text("a" * 64)
        assert client.get(endpoint).json()["scenes"][0]["state"] == "ready"


def test_authentication_and_malformed_plan_ids(tmp_path):
    with preview_client(tmp_path, api_token="isolated-test-token") as (client, job_id, directory, _):
        endpoint = f"/jobs/{job_id}/production"
        assert client.get(endpoint).status_code == 401
        assert client.get(f"{endpoint}/scenes/scene_01/video").status_code == 401
        client.headers["Authorization"] = "Bearer isolated-test-token"
        save(directory, "video_plan.json", {"scenes": [scene("../../private"), scene("C:\\private"), scene(), scene()]})
        rows = client.get(endpoint).json()["scenes"]
        assert [s["id"] for s in rows] == ["scene_01"]
        assert client.get("/jobs/missing/production").status_code == 404
        assert "isolated-test-token" not in client.get(endpoint).text


def test_plan_and_scene_symlinks_are_rejected(tmp_path):
    with preview_client(tmp_path) as (client, job_id, directory, _):
        secret = tmp_path / "private.json"
        secret.write_text(json.dumps({"scenes": [scene()]}), encoding="utf-8")
        try:
            (directory / "video_plan.json").symlink_to(secret)
        except OSError:
            pytest.skip("Creating symlinks requires OS permission")
        endpoint = f"/jobs/{job_id}/production"
        assert client.get(endpoint).json()["scenes"] == []
        (directory / "video_plan.json").unlink()
        save(directory, "video_plan.json", {"scenes": [scene()]})
        external = tmp_path / "external-scenes"
        external.mkdir()
        (directory / "scenes").symlink_to(external, target_is_directory=True)
        assert client.get(endpoint).json()["scenes"][0]["state"] == "planned"
        assert client.get(f"{endpoint}/scenes/scene_01/video").status_code == 409


def test_snapshot_limits_uncached_probe_work_per_poll(tmp_path, monkeypatch):
    directory = tmp_path / "job1"
    directory.mkdir()
    save(directory, "video_plan.json", {"scenes": [scene(), scene("scene_02")]})
    clock = iter([0, 0, 3])
    inspected = []
    monkeypatch.setattr(production, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(production, "FFmpeg", lambda settings: None)
    monkeypatch.setattr(production, "_ready_clip", lambda directory, scene_id, *args: inspected.append(scene_id))
    result = production._snapshot(SimpleNamespace(output_dir=tmp_path), SimpleNamespace(id="job1", topic="测试"))
    assert inspected == ["scene_01"]
    assert result["previews_pending"] is True
    assert len(result["scenes"]) == 2
    assert all(row["state"] == "planned" for row in result["scenes"])
