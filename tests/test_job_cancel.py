"""Isolated cancellation regressions; no model calls or video acceptance."""
import asyncio
import json
import os
from pathlib import Path
import sys
import threading
import time

from fastapi.testclient import TestClient
import pytest

from api.job_process import ProcessCleanupError, _identity, recover_workers, run_isolated
from api.main import create_app
from harness.schemas import JobCreate
from harness.settings import Settings
from storage.repository import JobRepository


def settings_for(tmp_path, **changes):
    return Settings(_env_file=None, project_root=tmp_path, output_dir=tmp_path / "outputs",
                    database_url="sqlite:///:memory:", **changes)


def wait_status(client, job_id, target):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] == target:
            return job
        time.sleep(.01)
    raise AssertionError(f"Expected {target}, got {job['status']}")


def test_public_stop_keeps_slot_until_cleanup_then_worker_accepts_next_job(tmp_path):
    entered_cleanup, release_cleanup = threading.Event(), threading.Event()
    repository = JobRepository("sqlite:///:memory:")

    class Producer:
        def __init__(self, _, repo):
            self.repo = repo

        async def run(self, job_id):
            self.repo.update(job_id, status="running", stage="rendering")
            try:
                await asyncio.Event().wait()
            finally:
                entered_cleanup.set()
                while not release_cleanup.is_set():
                    await asyncio.sleep(.01)

    app = create_app(settings_for(tmp_path, public_mode=True), repository=repository, orchestrator_factory=Producer)
    with TestClient(app) as client:
        first = client.post("/jobs", json={"topic": "first"}).json()["id"]
        wait_status(client, first, "running")
        assert client.post(f"/jobs/{first}/cancel").status_code == 202
        assert entered_cleanup.wait(2)
        assert client.get("/generation-state").json()["active_job"]["status"] == "cancelling"
        assert client.post("/jobs", json={"topic": "too-early"}).status_code == 409
        assert client.post(f"/jobs/{first}/cancel").status_code == 202
        # A late writer must not resurrect the cancelled work or report success.
        repository.update(first, status="succeeded", stage="complete", progress=1)
        assert repository.get(first).status == "cancelling"
        release_cleanup.set()
        wait_status(client, first, "cancelled")
        assert client.get("/generation-state").json()["busy"] is False
        assert client.post(f"/jobs/{first}/resume").status_code == 409
        assert client.post(f"/jobs/{first}/cancel").status_code == 202
        second = client.post("/jobs", json={"topic": "next"})
        assert second.status_code == 202
        wait_status(client, second.json()["id"], "running")
        client.post(f"/jobs/{second.json()['id']}/cancel")
        wait_status(client, second.json()["id"], "cancelled")
    repository.close()


def test_cancel_queued_job_is_never_executed(tmp_path):
    started = []

    class Producer:
        def __init__(self, _, repo):
            self.repo = repo

        async def run(self, job_id):
            started.append(job_id)
            self.repo.update(job_id, status="running")
            await asyncio.Event().wait()

    app = create_app(settings_for(tmp_path, local_workers=1), orchestrator_factory=Producer)
    with TestClient(app) as client:
        first = client.post("/jobs", json={"topic": "first"}).json()["id"]
        wait_status(client, first, "running")
        queued = client.post("/jobs", json={"topic": "queued"}).json()["id"]
        assert client.post(f"/jobs/{queued}/cancel").json()["status"] == "cancelled"
        client.post(f"/jobs/{first}/cancel")
        wait_status(client, first, "cancelled")
        next_job = client.post("/jobs", json={"topic": "next"}).json()["id"]
        wait_status(client, next_job, "running")
        assert queued not in started


def test_cancelled_and_interrupted_stop_do_not_resume_after_restart(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    stopped = repository.create(JobCreate(topic="stopped"))
    stopping = repository.create(JobCreate(topic="interrupted-stop"))
    repository.update(stopped.id, status="cancelling")
    repository.update(stopped.id, status="cancelled", stage="cancelled")
    repository.update(stopping.id, status="cancelling", stage="cancelling")
    directory = tmp_path / "outputs" / stopped.id
    directory.mkdir(parents=True)
    evidence = directory / "model_calls.json"
    evidence.write_text("[]")

    class NeverRun:
        def __init__(self, *_):
            raise AssertionError("Cancelled task must not execute")

    app = create_app(settings_for(tmp_path, public_mode=True), repository=repository, orchestrator_factory=NeverRun)
    with TestClient(app) as client:
        assert client.get("/generation-state").json()["busy"] is False
        assert repository.get(stopping.id).status == "cancelled"
        assert evidence.read_text() == "[]"
        assert client.post(f"/jobs/{stopped.id}/resume").status_code == 409
    repository.close()


def test_shutdown_is_not_a_user_cancellation(tmp_path):
    repository = JobRepository("sqlite:///:memory:")

    class Producer:
        def __init__(self, _, repo):
            self.repo = repo

        async def run(self, job_id):
            self.repo.update(job_id, status="running")
            await asyncio.Event().wait()

    app = create_app(settings_for(tmp_path), repository=repository, orchestrator_factory=Producer)
    with TestClient(app) as client:
        job_id = client.post("/jobs", json={"topic": "restartable"}).json()["id"]
        wait_status(client, job_id, "running")
    assert repository.get(job_id).status == "running"
    assert [job.id for job in repository.pending()] == [job_id]
    repository.close()


def test_cancel_auth_terminal_states_and_missing_job(tmp_path):
    repository = JobRepository("sqlite:///:memory:")
    app = create_app(settings_for(tmp_path, api_token="fixture"), repository=repository)
    with TestClient(app) as client:
        assert client.post("/jobs/missing/cancel").status_code == 401
        client.headers["Authorization"] = "Bearer fixture"
        assert client.post("/jobs/missing/cancel").status_code == 404
        for status in ("failed", "succeeded"):
            job = repository.create(JobCreate(topic=status))
            repository.update(job.id, status=status)
            assert client.post(f"/jobs/{job.id}/cancel").status_code == 409
    repository.close()


@pytest.mark.asyncio
async def test_real_process_cancellation_stops_detached_renderer_descendant(tmp_path):
    heartbeat = tmp_path / "heartbeat.txt"
    child_pid = tmp_path / "child.pid"
    child = tmp_path / "child.py"
    child.write_text("import time, pathlib, signal, os\n"
                     "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                     f"pathlib.Path({str(child_pid)!r}).write_text(str(os.getpid()))\n"
                     "while True:\n"
                     f" pathlib.Path({str(heartbeat)!r}).write_text(str(time.time_ns()))\n"
                     " time.sleep(.03)\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text("import sys, subprocess, json, time\n"
                      "settings=json.load(sys.stdin)\n"
                      f"subprocess.Popen([sys.executable,{str(child)!r}],start_new_session={os.name != 'nt'})\n"
                      "time.sleep(120)\n", encoding="utf-8")
    task = asyncio.create_task(run_isolated(settings_for(tmp_path), "fixture",
                                            command=[sys.executable, str(runner)]))
    try:
        for _ in range(200):
            if heartbeat.exists():
                break
            await asyncio.sleep(.02)
        assert heartbeat.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        saved = heartbeat.read_text()
        await asyncio.sleep(.2)
        assert heartbeat.read_text() == saved
        if sys.platform.startswith("linux"):
            stat = Path(f"/proc/{child_pid.read_text()}/stat")
            assert not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.asyncio
async def test_config_snapshot_uses_private_stdin_and_spawn_cancel_is_safe(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    runner = tmp_path / "stdin_check.py"
    runner.write_text("import json,sys,pathlib\n"
                      "value=json.load(sys.stdin)\n"
                      f"pathlib.Path({str(snapshot)!r}).write_text(json.dumps({{'key':value['model_api_key'],'args':sys.argv}}))\n", encoding="utf-8")
    assert await run_isolated(settings_for(tmp_path, model_api_key="fixture-secret"), "fixture",
                              command=[sys.executable, str(runner)]) == 0
    saved = json.loads(snapshot.read_text())
    assert saved["key"] == "fixture-secret"
    assert "fixture-secret" not in " ".join(saved["args"])


def test_separate_repository_connection_cannot_overwrite_stop(tmp_path):
    url = f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"
    first, second = JobRepository(url), JobRepository(url)
    try:
        job = first.create(JobCreate(topic="shared-process-row"))
        first.update(job.id, status="running")
        second.update(job.id, status="cancelling")
        assert first.update(job.id, status="succeeded", output_path="partial.mp4").status == "cancelling"
        second.update(job.id, status="cancelled")
        assert first.update(job.id, status="running", stage="late-write").status == "cancelled"
        assert first.pending() == []
    finally:
        first.close()
        second.close()


def test_unconfirmed_cleanup_never_releases_capacity_even_after_success(tmp_path):
    class Producer:
        def __init__(self, _, repo):
            self.repo = repo

        async def run(self, job_id):
            self.repo.update(job_id, status="succeeded", stage="complete")
            raise ProcessCleanupError("isolated cleanup refusal")

    app = create_app(settings_for(tmp_path, public_mode=True), orchestrator_factory=Producer)
    with TestClient(app) as client:
        job_id = client.post("/jobs", json={"topic": "blocked-cleanup"}).json()["id"]
        wait_status(client, job_id, "cancelling")
        assert client.get("/generation-state").json()["busy"] is True
        assert client.post("/jobs", json={"topic": "cannot-overlap"}).status_code == 409


def test_default_subprocess_runner_persists_real_orchestrator_failure_and_telemetry(tmp_path):
    settings = settings_for(tmp_path, model_name="", model_api_key="", minimax_api_key="").model_copy(
        update={"database_url": f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}"})
    # Uses the real private runner/Settings/SQLite/Orchestrator. Missing model
    # configuration fails before opening a provider connection; no video fixture.
    with TestClient(create_app(settings)) as client:
        job_id = client.post("/jobs", json={"topic": "isolated missing configuration"}).json()["id"]
        record = wait_status(client, job_id, "failed")
        assert "ModelError" in record["error"]
        assert "MODEL_NAME" in record["error"]
        assert record["stage"] == "identify"
        deadline = time.monotonic() + 8
        while client.get("/generation-state").json()["busy"] and time.monotonic() < deadline:
            time.sleep(.01)
        assert client.get("/generation-state").json()["busy"] is False
        record = client.get(f"/jobs/{job_id}").json()
        assert record["telemetry"]["stages"]["identify"]["status"] == "failed"
        state = json.loads((settings.output_dir / job_id / "telemetry_state.json").read_text(encoding="utf-8"))
        assert state["runs"][-1]["completed_at"]
        assert not (settings.output_dir / job_id / ".worker-process.json").exists()


def test_telemetry_retries_transient_windows_reader_sharing_violation(tmp_path, monkeypatch):
    import harness.telemetry as telemetry
    save, attempts = telemetry.save_json, []

    def temporarily_shared(path, value):
        attempts.append(1)
        if len(attempts) < 3:
            failure = PermissionError("fixture reader still holds file")
            failure.winerror = 32
            raise failure
        save(path, value)

    monkeypatch.setattr(telemetry, "save_json", temporarily_shared)
    repository = JobRepository("sqlite:///:memory:")
    try:
        job = repository.create(JobCreate(topic="sharing fixture"))
        clock = telemetry.JobTelemetry(repository, job.id, tmp_path)
        clock.start_run()
        assert len(attempts) == 3
        assert repository.get(job.id).telemetry["timing_recorded"] is True
    finally:
        repository.close()


@pytest.mark.asyncio
async def test_recovery_ignores_recycled_pid_identity(tmp_path):
    marker = tmp_path / "job" / ".worker-process.json"
    marker.parent.mkdir()
    # A real unrelated child, but the marker's recorded birth does not match.
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)")
    try:
        marker.write_text(json.dumps({"pid": process.pid, "birth": "wrong-birth"}))
        await recover_workers(tmp_path)
        assert not marker.exists()
        assert process.returncode is None
    finally:
        process.kill()
        await process.wait()


@pytest.mark.asyncio
async def test_restart_reconciles_previous_alive_worker_before_releasing_slot(tmp_path):
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux production recovery")
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)",
                                                   start_new_session=True)
    marker = tmp_path / "job" / ".worker-process.json"
    marker.parent.mkdir()
    try:
        marker.write_text(json.dumps({"pid": process.pid, "birth": _identity(process.pid)}))
        await recover_workers(tmp_path)
        await asyncio.wait_for(process.wait(), 3)
        assert process.returncode is not None
        assert not marker.exists()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_runner_reaps_orphaned_detached_grandchild_before_normal_exit(tmp_path):
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux subreaper production behavior")
    heartbeat = tmp_path / "orphan-heartbeat"
    child = tmp_path / "orphan.py"
    child.write_text("import time,pathlib\nwhile True:\n"
                     f" pathlib.Path({str(heartbeat)!r}).write_text(str(time.time_ns()))\n"
                     " time.sleep(.02)\n", encoding="utf-8")
    middle = tmp_path / "middle.py"
    middle.write_text(f"import subprocess,sys\nsubprocess.Popen([sys.executable,{str(child)!r}],start_new_session=True)\n", encoding="utf-8")
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text("import asyncio,subprocess,sys,pathlib\nimport api.job_runner as runner\n"
                       "class Fixture:\n"
                       " def __init__(self,s,r): self.r=r\n"
                       " async def run(self,j):\n"
                       f"  subprocess.run([sys.executable,{str(middle)!r}],check=True)\n"
                       f"  while not pathlib.Path({str(heartbeat)!r}).exists(): await asyncio.sleep(.01)\n"
                       "  self.r.update(j,status='succeeded')\n"
                       "runner.Orchestrator=Fixture\nrunner.main()\n", encoding="utf-8")
    settings = settings_for(tmp_path).model_copy(update={"database_url": f"sqlite:///{tmp_path / 'jobs.db'}"})
    repository = JobRepository(settings.database_url)
    job = repository.create(JobCreate(topic="isolated orphan check"))
    try:
        result = await run_isolated(settings, job.id, command=[sys.executable, str(wrapper), job.id])
        assert result == 0
        assert repository.get(job.id).status == "succeeded"
        saved = heartbeat.read_text()
        await asyncio.sleep(.2)
        assert heartbeat.read_text() == saved
        assert not (settings.output_dir / job.id / ".worker-process.json").exists()
    finally:
        repository.close()
