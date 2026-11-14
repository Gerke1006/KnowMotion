"""Record deletion uses isolated databases and never removes production files."""
from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from api.main import create_app
from harness.schemas import JobCreate
from harness.settings import Settings
from storage.repository import JobRepository


@contextmanager
def delete_client(tmp_path, **options):
    settings = Settings(_env_file=None, project_root=tmp_path, output_dir=tmp_path / "outputs",
                        database_url=f"sqlite:///{(tmp_path / 'isolated.db').as_posix()}", **options)
    repository = JobRepository(settings.database_url)
    app = create_app(settings, repository=repository)
    with TestClient(app) as client:
        yield client, repository, settings, app
    repository.close()


def make_job(repository, status):
    job = repository.create(JobCreate(topic=f"隔离删除测试：{status}"))
    return repository.update(job.id, status=status)


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_terminal_deletion_is_persistent_and_preserves_artifacts(tmp_path, status):
    with delete_client(tmp_path) as (client, repository, settings, _):
        job = make_job(repository, status)
        other = make_job(repository, "succeeded")
        directory = settings.output_dir / job.id
        directory.mkdir(parents=True)
        video = directory / "final.mp4"
        video.write_bytes(b"isolated-retained-video")
        audit = directory / "live_acceptance.json"
        audit.write_text('{"fixture":true}', encoding="utf-8")
        repository.update(job.id, output_path=str(video), artifacts={"live_acceptance.json": str(audit)})
        endpoint = f"/jobs/{job.id}"
        assert client.get(endpoint).status_code == 200
        response = client.delete(endpoint)
        assert response.status_code == 204
        assert response.content == b""
        assert client.delete(endpoint).status_code == 404
        assert repository.get(job.id) is None
        assert [item["id"] for item in client.get("/jobs").json()] == [other.id]
        for suffix in ("", "/video", "/production", "/thumbnail", "/artifacts/live_acceptance.json"):
            assert client.get(endpoint + suffix).status_code == 404
        assert video.read_bytes() == b"isolated-retained-video"
        assert audit.read_text(encoding="utf-8") == '{"fixture":true}'
        assert repository.get(other.id) is not None
        second_connection = JobRepository(settings.database_url)
        try:
            assert second_connection.get(job.id) is None
            assert second_connection.get(other.id) is not None
        finally:
            second_connection.close()


def test_delete_authentication_and_missing_job(tmp_path):
    with delete_client(tmp_path, api_token="isolated-delete-token") as (client, repository, _, _):
        job = make_job(repository, "failed")
        assert client.delete(f"/jobs/{job.id}").status_code == 401
        assert client.delete("/jobs/missing").status_code == 401
        assert repository.get(job.id) is not None
        client.headers["Authorization"] = "Bearer isolated-delete-token"
        assert client.delete("/jobs/missing").status_code == 404
        assert client.delete(f"/jobs/{job.id}").status_code == 204


@pytest.mark.parametrize("status", ["queued", "running"])
def test_active_jobs_cannot_be_deleted(tmp_path, status):
    with delete_client(tmp_path) as (client, repository, _, _):
        # Created after startup, so the isolated job is never dispatched.
        job = make_job(repository, status)
        assert client.delete(f"/jobs/{job.id}").status_code == 409
        assert repository.get(job.id).status == status
        assert repository.delete_terminal(job.id) == "active"
        assert repository.delete_terminal("missing") == "not_found"


def test_atomic_status_predicate_rejects_resume_after_api_read(tmp_path, monkeypatch):
    with delete_client(tmp_path) as (client, repository, _, _):
        job = make_job(repository, "failed")
        original_delete = repository.delete_terminal

        def concurrently_resumed(job_id):
            repository.update(job_id, status="running")
            return original_delete(job_id)

        monkeypatch.setattr(repository, "delete_terminal", concurrently_resumed)
        assert client.delete(f"/jobs/{job.id}").status_code == 409
        assert repository.get(job.id).status == "running"


def test_temporal_live_retry_blocks_deletion_and_settled_workflow_allows_it(tmp_path):
    temporal = pytest.importorskip("temporalio.client")
    with delete_client(tmp_path) as (client, repository, _, app):
        job = make_job(repository, "failed")

        class Workflow:
            status = temporal.WorkflowExecutionStatus.RUNNING
            unavailable = False

            def get_workflow_handle(self, workflow_id):
                assert workflow_id == f"video-{job.id}"
                return self

            async def describe(self):
                if self.unavailable:
                    raise RuntimeError("isolated offline fixture")
                return SimpleNamespace(status=self.status)

        workflow = Workflow()
        app.state.backend = "temporal"
        app.state.temporal = workflow
        assert client.delete(f"/jobs/{job.id}").status_code == 409
        assert repository.get(job.id) is not None
        workflow.unavailable = True
        assert client.delete(f"/jobs/{job.id}").status_code == 503
        assert repository.get(job.id) is not None
        workflow.unavailable = False
        workflow.status = temporal.WorkflowExecutionStatus.FAILED
        assert client.delete(f"/jobs/{job.id}").status_code == 204


def test_temporal_completed_workflow_allows_deletion(tmp_path):
    temporal = pytest.importorskip("temporalio.client")
    with delete_client(tmp_path) as (client, repository, _, app):
        job = make_job(repository, "succeeded")

        class Workflow:
            def get_workflow_handle(self, _):
                return self

            async def describe(self):
                return SimpleNamespace(status=temporal.WorkflowExecutionStatus.COMPLETED)

        app.state.backend = "temporal"
        app.state.temporal = Workflow()
        assert client.delete(f"/jobs/{job.id}").status_code == 204
