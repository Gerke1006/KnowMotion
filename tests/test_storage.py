from pathlib import Path

import pytest

from harness.schemas import JobCreate
from storage.artifacts import LocalArtifactStore, S3ArtifactStore, object_key
from storage.repository import JobRepository


def test_jobs_survive_reopen_and_keep_request(tmp_path):
    url = f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"
    repository = JobRepository(url)
    job = repository.create(JobCreate(topic="微积分", mode="demo", renderer="canvas"))
    repository.update(job.id, status="running", stage="planning", progress=0.3)
    repository.close()
    reopened = JobRepository(url)
    try:
        saved = reopened.get(job.id)
        assert saved.request.renderer == "canvas"
        assert saved.progress == 0.3
        assert [item.id for item in reopened.pending()] == [job.id]
        reopened.update(job.id, status="succeeded", progress=1)
        assert reopened.pending() == []
        assert reopened.list(1)[0].id == job.id
        with pytest.raises(ValueError):
            reopened.update(job.id, topic="Changed")
        with pytest.raises(KeyError):
            reopened.update("missing", stage="planning")
    finally:
        reopened.close()


def test_local_artifact_store_rejects_traversal(tmp_path):
    store = LocalArtifactStore(tmp_path / "store")
    source = tmp_path / "source.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    target = Path(store.put_file("job-1", "plans/request.json", source))
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    for name in ("../private.env", "/etc/passwd", "..\\secret", "C:/secret", ""):
        with pytest.raises(ValueError):
            store.get_path("job-1", name)
    with pytest.raises(ValueError):
        object_key("../job", "plan.json")


def test_s3_adapter_keeps_namespace_and_never_guesses_public_url(tmp_path):
    calls = []

    class Client:
        def upload_file(self, *args):
            calls.append(args)

        def generate_presigned_url(self, operation, **kwargs):
            assert operation == "get_object"
            assert kwargs["Params"] == {"Bucket": "videos", "Key": "job-1/final.mp4"}
            return "https://storage.test/signed"

    store = S3ArtifactStore("videos", client=Client())
    source = tmp_path / "final.mp4"
    source.write_bytes(b"video")
    assert store.put_file("job-1", "final.mp4", source) == "s3://videos/job-1/final.mp4"
    assert calls == [(str(source), "videos", "job-1/final.mp4")]
    assert store.presigned_url("job-1", "final.mp4") == "https://storage.test/signed"
