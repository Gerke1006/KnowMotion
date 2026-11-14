"""Isolated API safety/concurrency regressions; these are not video acceptance."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from harness.schemas import JobCreate
from harness.settings import Settings
from storage.repository import JobRepository


class BlockedProducer:
    def __init__(self, settings, repository):
        self.repository = repository

    async def run(self, job_id):
        self.repository.update(job_id, status="running", stage="research", progress=.15)
        await asyncio.Event().wait()


def public_settings(tmp_path, **changes):
    return Settings(_env_file=None, project_root=tmp_path, output_dir=tmp_path / "outputs",
                    database_url="sqlite:///:memory:", public_mode=True, **changes)


def test_public_visitors_share_one_atomic_admission_slot(tmp_path):
    # Even an accidental high local worker setting cannot increase public concurrency.
    app = create_app(public_settings(tmp_path, local_workers=8, api_token="fixture-admin-token"),
                     orchestrator_factory=BlockedProducer)
    with TestClient(app) as client:
        config = client.get("/ui-config").json()
        assert config == {"requires_auth": False, "public_mode": True,
                          "can_edit_settings": False, "can_delete_jobs": False,
                          "single_generation": True, "can_cancel_jobs": True}
        assert client.get("/generation-state").json() == {"busy": False, "active_job": None}
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda i: client.post("/jobs", json={"topic": f"topic-{i}"}), range(8)))
        assert sorted(r.status_code for r in responses) == [202] + [409] * 7
        admitted = next(r.json() for r in responses if r.status_code == 202)
        for response in responses:
            if response.status_code == 409:
                assert response.json()["detail"]["active_job_id"] == admitted["id"]
                assert response.json()["detail"]["code"] == "generation_busy"
        state = client.get("/generation-state")
        assert state.headers["cache-control"] == "no-store"
        assert state.json()["busy"] is True
        assert state.json()["active_job"]["id"] == admitted["id"]
        assert state.json()["active_job"]["stage"] == "research"
        assert state.json()["active_job"]["progress"] == .15
        assert len(client.get("/jobs").json()) == 1


def test_create_and_resume_compete_for_the_same_slot(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    failed = repository.create(JobCreate(topic="previous-failure"))
    repository.update(failed.id, status="failed", error="fixture failure")
    app = create_app(public_settings(tmp_path), repository=repository, orchestrator_factory=BlockedProducer)
    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            create = pool.submit(client.post, "/jobs", json={"topic": "new-topic"})
            resume = pool.submit(client.post, f"/jobs/{failed.id}/resume")
            responses = [create.result(), resume.result()]
        assert sorted(response.status_code for response in responses) == [202, 409]
        assert len(repository.pending()) == 1
    repository.close()


def test_public_management_and_internal_artifacts_are_not_exposed(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="shared-content"))
    repository.update(job.id, status="failed", error="fixture-internal-error", output_path="/private/final.mp4",
                      artifacts={"internal": "/private/model-request.json"})
    app = create_app(public_settings(tmp_path), repository=repository, orchestrator_factory=BlockedProducer)
    with TestClient(app) as client:
        for method, path in [("GET", "/settings/api"), ("PUT", "/settings/api"), ("DELETE", "/settings/api"),
                             ("DELETE", f"/jobs/{job.id}"), ("GET", f"/jobs/{job.id}/artifacts/internal")]:
            assert client.request(method, path).status_code == 403
        response = client.get(f"/jobs/{job.id}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["artifacts"] == {}
        assert response.json()["output_path"] == f"/jobs/{job.id}/video"
        assert "fixture-internal-error" not in response.text
        assert "/private/" not in response.text
        assert repository.get(job.id).error == "fixture-internal-error"
        assert client.get("/domains").status_code == 200
        assert client.get("/generation-state").json()["busy"] is False
    repository.close()


@pytest.mark.parametrize("changes", [{"mode": "demo"}, {"tts_enabled": False}, {"width": 3840}, {"fps": 60},
                                      {"duration": 600}, {"narration_char_budget": 5000}, {"renderer": "blender"}])
def test_public_requests_use_live_pipeline_with_bounded_resources(tmp_path, changes):
    app = create_app(public_settings(tmp_path), orchestrator_factory=BlockedProducer)
    with TestClient(app) as client:
        assert client.post("/jobs", json={"topic": "topic", **changes}).status_code == 422
        assert client.get("/generation-state").json()["busy"] is False


def test_public_worker_always_uses_narration_and_validates_old_resumes(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    old = repository.create(JobCreate(topic="old-demo", mode="demo"))
    repository.update(old.id, status="failed")
    snapshots = []

    class Producer(BlockedProducer):
        def __init__(self, settings, repository):
            super().__init__(settings, repository)
            snapshots.append(settings)

    app = create_app(public_settings(tmp_path, tts_enabled=False), repository=repository,
                     orchestrator_factory=Producer)
    with TestClient(app) as client:
        assert client.post(f"/jobs/{old.id}/resume").status_code == 422
        assert repository.get(old.id).status == "failed"
        assert client.post("/jobs", json={"topic": "new-live"}).status_code == 202
        # A second request allows the event loop to start the queued worker.
        assert client.get("/generation-state").json()["busy"] is True
        assert len(snapshots) == 1
        assert snapshots[0].tts_enabled is True
    repository.close()


def test_public_mode_rejects_a_second_api_owner(tmp_path):
    first = create_app(public_settings(tmp_path), orchestrator_factory=BlockedProducer)
    second = create_app(public_settings(tmp_path), orchestrator_factory=BlockedProducer)
    with TestClient(first):
        with pytest.raises(RuntimeError, match="already has an API owner"):
            with TestClient(second):
                pass
    # Normal shutdown relinquishes ownership and restart works without cleanup.
    with TestClient(second) as client:
        assert client.get("/health").status_code == 200


def test_failed_frozen_history_cannot_be_resumed_from_public_ui(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    job = repository.create(JobCreate(topic="history", domain="history"))
    repository.update(job.id, status="failed")
    folder = tmp_path / "outputs" / job.id
    folder.mkdir(parents=True)
    (folder / "run_manifest.json").write_text("{}")
    app = create_app(public_settings(tmp_path), repository=repository, orchestrator_factory=BlockedProducer)
    with TestClient(app) as client:
        assert client.post(f"/jobs/{job.id}/resume").status_code == 409
        assert repository.get(job.id).status == "failed"
    repository.close()
