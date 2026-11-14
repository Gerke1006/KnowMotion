import asyncio
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from harness.schemas import JobCreate
from harness.settings import Settings
from storage.repository import JobRepository


class SuccessfulProducer:
    def __init__(self, settings, repository):
        self.settings = settings
        self.repository = repository

    async def run(self, job_id):
        self.repository.update(job_id, status="running", stage="rendering", progress=0.8)
        directory = Path(self.settings.output_dir) / job_id
        directory.mkdir(parents=True, exist_ok=True)
        video = directory / "final.mp4"
        video.write_bytes(b"test-video")
        plan = directory / "video_plan.json"
        plan.write_text('{"topic":"test"}', encoding="utf-8")
        return self.repository.update(job_id, status="succeeded", stage="complete", progress=1,
                                      output_path=str(video), artifacts={"video_plan.json": str(plan)})


def settings_for(tmp_path, **changes):
    changes.setdefault("project_root", tmp_path)
    return Settings(_env_file=None, output_dir=tmp_path / "outputs", database_url="sqlite:///:memory:", **changes)


def wait_for_job(client, job_id, status="succeeded"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{job_id}")
        if response.json()["status"] == status:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"Job did not reach {status}")


def test_submit_process_and_download_without_external_calls(tmp_path):
    app = create_app(settings_for(tmp_path), orchestrator_factory=SuccessfulProducer)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert len(client.get("/domains").json()) == 6
        response = client.post("/jobs", json={"topic": "导数", "mode": "demo", "renderer": "canvas"})
        assert response.status_code == 202
        job_id = response.json()["id"]
        wait_for_job(client, job_id)
        assert client.get(f"/jobs/{job_id}/video").content == b"test-video"
        partial = client.get(f"/jobs/{job_id}/video", headers={"Range": "bytes=0-3"})
        assert partial.status_code == 206
        assert partial.content == b"test"
        assert client.get(f"/jobs/{job_id}/artifacts/video_plan.json").json() == {"topic": "test"}
        assert client.get("/jobs").json()[0]["id"] == job_id
        assert client.get("/jobs/missing").status_code == 404
        assert client.post("/jobs", json={"topic": "  "}).status_code == 422


def test_auth_and_artifact_path_confinement(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    app = create_app(settings_for(tmp_path, api_token="local-test-token"), repository=repository,
                     orchestrator_factory=SuccessfulProducer)
    with TestClient(app) as client:
        assert client.get("/jobs").status_code == 401
        client.headers["Authorization"] = "Bearer local-test-token"
        response = client.post("/jobs", json={"topic": "导数", "mode": "demo"})
        job_id = response.json()["id"]
        wait_for_job(client, job_id)
        secret = tmp_path / "private.txt"
        secret.write_text("private", encoding="utf-8")
        repository.update(job_id, output_path=str(secret), artifacts={"leak": str(secret)})
        assert client.get(f"/jobs/{job_id}/video").status_code == 404
        assert client.get(f"/jobs/{job_id}/artifacts/leak").status_code == 404
    repository.close()


def test_queue_admission_limit(tmp_path):
    class BlockedProducer:
        def __init__(self, *_):
            pass

        async def run(self, _):
            await asyncio.Event().wait()

    app = create_app(settings_for(tmp_path, max_queued_jobs=1), orchestrator_factory=BlockedProducer)
    with TestClient(app) as client:
        assert client.post("/jobs", json={"topic": "first"}).status_code == 202
        assert client.post("/jobs", json={"topic": "second"}).status_code == 429


def test_restart_resumes_incomplete_jobs(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="导数", mode="demo"))
    repository.update(job.id, status="running", stage="storyboard", progress=0.5)
    app = create_app(settings_for(tmp_path), repository=repository, orchestrator_factory=SuccessfulProducer)
    with TestClient(app) as client:
        assert wait_for_job(client, job.id)["progress"] == 1
    repository.close()


@pytest.mark.parametrize("token,requires_auth", [("", False), ("fixture-secret", True)])
def test_frontend_is_public_but_job_api_keeps_authentication(tmp_path, token, requires_auth):
    frontend = tmp_path / "frontend" / "dist"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text('<html><script src="/assets/app.js"></script></html>', encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("window.ready = true", encoding="utf-8")
    (tmp_path / "private.txt").write_text("private", encoding="utf-8")
    app = create_app(settings_for(tmp_path, project_root=tmp_path, api_token=token))
    with TestClient(app) as client:
        for path in ("/", "/workspace", "/workspace/", "/workspace?view=library", "/workspace?job=existing-job"):
            page = client.get(path, follow_redirects=False)
            assert page.status_code == 200
            assert page.headers["content-type"].startswith("text/html")
            assert page.headers["cache-control"] == "no-cache"
            assert '<script src="/assets/app.js">' in page.text
            assert "fixture-secret" not in page.text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/%2e%2e/%2e%2e/private.txt").status_code == 404
        assert client.get("/workspace/not-a-page").status_code == 404
        assert client.get("/not-an-api").status_code == 404
        config = client.get("/ui-config")
        assert config.json() == {"requires_auth": requires_auth, "public_mode": False,
                                 "can_edit_settings": True, "can_delete_jobs": True,
                                 "single_generation": False, "can_cancel_jobs": True}
        assert "fixture-secret" not in config.text + page.text
        assert client.get("/jobs").status_code == (401 if requires_auth else 200)
        assert client.get("/jobs/missing").status_code == (401 if requires_auth else 404)


def test_frontend_missing_build_explains_how_to_start(tmp_path):
    app = create_app(settings_for(tmp_path, project_root=tmp_path))
    with TestClient(app) as client:
        for path in ("/", "/workspace", "/workspace/"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 503
            assert "npm run build" in response.json()["detail"]
        assert client.get("/health").status_code == 200


def test_resume_failed_job_preserves_identity_and_rejects_completed_jobs(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="retry-original-topic", mode="live"))
    repository.update(job.id, status="failed", stage="rendering", progress=0.8, error="temporary failure")
    app = create_app(settings_for(tmp_path, api_token="fixture-token"), repository=repository,
                     orchestrator_factory=SuccessfulProducer)
    with TestClient(app) as client:
        endpoint = f"/jobs/{job.id}/resume"
        assert client.post(endpoint).status_code == 401
        client.headers["Authorization"] = "Bearer fixture-token"
        response = client.post(endpoint)
        assert response.status_code == 202
        assert response.json()["id"] == job.id
        assert response.json()["request"] == job.request.model_dump(mode="json")
        assert response.json()["error"] is None
        wait_for_job(client, job.id)
        assert client.post(endpoint).status_code == 409
        assert len(repository.list()) == 1
        assert client.post("/jobs/missing/resume").status_code == 404
    repository.close()


def test_resume_obeys_queue_capacity_and_rejects_duplicate_dispatch(tmp_path):
    class BlockedProducer:
        def __init__(self, *_):
            pass

        async def run(self, _):
            await asyncio.Event().wait()

    repository = JobRepository("sqlite:///:memory:")
    jobs = [repository.create(JobCreate(topic=f"topic-{i}")) for i in range(2)]
    for job in jobs:
        repository.update(job.id, status="failed", error="temporary")
    app = create_app(settings_for(tmp_path, max_queued_jobs=1), repository=repository,
                     orchestrator_factory=BlockedProducer)
    with TestClient(app) as client:
        assert client.post(f"/jobs/{jobs[0].id}/resume").status_code == 202
        assert client.post(f"/jobs/{jobs[0].id}/resume").status_code == 409
        response = client.post(f"/jobs/{jobs[1].id}/resume")
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "30"
        assert repository.get(jobs[1].id).status == "failed"
    repository.close()


def test_temporal_outbox_recovers_persisted_jobs_and_uses_stable_ids(tmp_path, monkeypatch):
    temporal_client = pytest.importorskip("temporalio.client")
    from temporalio.common import WorkflowIDReusePolicy

    calls = []

    class Client:
        async def start_workflow(self, _, job_id, **kwargs):
            calls.append((job_id, kwargs))

    async def connect(*_, **__):
        return Client()

    monkeypatch.setattr(temporal_client.Client, "connect", connect)
    repository = JobRepository("sqlite:///:memory:")
    existing = repository.create(JobCreate(topic="saved-before-crash", mode="demo"))
    app = create_app(settings_for(tmp_path, execution_backend="temporal"), repository=repository,
                     orchestrator_factory=SuccessfulProducer)
    with TestClient(app) as client:
        response = client.post("/jobs", json={"topic": "new", "mode": "demo"})
        assert response.status_code == 202
        created_id = response.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and {existing.id, created_id} - {item[0] for item in calls}:
            time.sleep(0.01)
        assert {existing.id, created_id} <= {item[0] for item in calls}
        for job_id, kwargs in calls:
            assert kwargs["id"] == f"video-{job_id}"
            assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE
    repository.close()


def test_temporal_terminal_failure_reconciles_stale_running_job(tmp_path, monkeypatch):
    temporal_client = pytest.importorskip("temporalio.client")
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.exceptions import WorkflowAlreadyStartedError
    from types import SimpleNamespace

    class Client:
        async def start_workflow(self, _, job_id, **kwargs):
            raise WorkflowAlreadyStartedError(kwargs["id"], "VideoProductionWorkflow")

        def get_workflow_handle(self, _):
            return self

        async def describe(self):
            return SimpleNamespace(status=WorkflowExecutionStatus.TIMED_OUT)

    async def connect(*_, **__):
        return Client()

    monkeypatch.setattr(temporal_client.Client, "connect", connect)
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="interrupted-job", mode="demo"))
    repository.update(job.id, status="running", stage="rendering")
    app = create_app(settings_for(tmp_path, execution_backend="temporal"), repository=repository,
                     orchestrator_factory=SuccessfulProducer)
    with TestClient(app) as client:
        result = wait_for_job(client, job.id, "failed")
        assert result["stage"] == "temporal"
        assert "TIMED_OUT" in result["error"]
    repository.close()


def test_temporal_resume_waits_for_terminal_failure_and_reuses_workflow_id(tmp_path, monkeypatch):
    temporal_client = pytest.importorskip("temporalio.client")
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.common import WorkflowIDReusePolicy
    from types import SimpleNamespace

    calls = []

    class Client:
        status = WorkflowExecutionStatus.RUNNING

        async def start_workflow(self, _, job_id, **kwargs):
            calls.append((job_id, kwargs))

        def get_workflow_handle(self, _):
            return self

        async def describe(self):
            return SimpleNamespace(status=self.status)

    temporal = Client()

    async def connect(*_, **__):
        return temporal

    monkeypatch.setattr(temporal_client.Client, "connect", connect)
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="failed-workflow"))
    repository.update(job.id, status="failed", error="activity failure")
    app = create_app(settings_for(tmp_path, execution_backend="temporal"), repository=repository)
    with TestClient(app) as client:
        endpoint = f"/jobs/{job.id}/resume"
        assert client.post(endpoint).status_code == 409
        assert repository.get(job.id).status == "failed"
        temporal.status = WorkflowExecutionStatus.FAILED
        assert client.post(endpoint).status_code == 202
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not calls:
            time.sleep(0.01)
        assert calls
        assert calls[0][0] == job.id
        assert calls[0][1]["id"] == f"video-{job.id}"
        assert calls[0][1]["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
    repository.close()
