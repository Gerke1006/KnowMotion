"""Run with ``uvicorn api.main:app --host 127.0.0.1 --port 8000``."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from harness.schemas import JobCreate, JobRecord
from storage.repository import JobRepository


def create_app(settings=None, *, repository=None, orchestrator_factory=None) -> FastAPI:
    if settings is None:
        from harness.settings import Settings
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repo = repository or JobRepository(settings.database_url)
        factory = orchestrator_factory
        if factory is None:
            from harness.orchestrator import Orchestrator
            factory = Orchestrator
        app.state.repository = repo
        app.state.queue = asyncio.Queue()
        app.state.admission_lock = asyncio.Lock()
        backend = getattr(settings, "execution_backend", "local")
        if backend not in {"local", "temporal"}:
            raise RuntimeError("execution_backend must be local or temporal")
        app.state.backend = backend
        tasks = []
        if backend == "local":
            # A single API process owns this development queue. For multi-process
            # or multi-host deployment use Temporal with a shared PostgreSQL DB.
            for record in repo.pending():
                repo.update(record.id, status="queued", stage="resuming", error=None)
                app.state.queue.put_nowait(record.id)

            async def worker():
                while True:
                    job_id = await app.state.queue.get()
                    try:
                        await factory(settings, repo).run(job_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        repo.update(job_id, status="failed", stage="failed", error="Video production failed; inspect worker logs and job artifacts.")
                    finally:
                        app.state.queue.task_done()

            for _ in range(max(1, min(32, int(getattr(settings, "local_workers", 2))))):
                tasks.append(asyncio.create_task(worker()))
        else:
            from temporalio.client import Client, WorkflowExecutionStatus
            from temporalio.common import WorkflowIDReusePolicy
            from temporalio.exceptions import WorkflowAlreadyStartedError
            from workflows.temporal import VideoProductionWorkflow

            app.state.temporal = await Client.connect(
                getattr(settings, "temporal_address", "localhost:7233"),
                namespace=getattr(settings, "temporal_namespace", "default"),
            )
            app.state.dispatch_wake = asyncio.Event()

            async def dispatcher():
                # The jobs table is the outbox: a crash after INSERT or a lost
                # start-workflow response cannot permanently strand a job.
                while True:
                    app.state.dispatch_wake.clear()
                    for record in repo.pending():
                        try:
                            await app.state.temporal.start_workflow(
                                VideoProductionWorkflow.run, record.id,
                                id=f"video-{record.id}",
                                task_queue=getattr(settings, "temporal_task_queue", "vibe-video"),
                                id_reuse_policy=(
                                    WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                                    if record.stage == "resuming"
                                    else WorkflowIDReusePolicy.REJECT_DUPLICATE
                                ),
                            )
                        except WorkflowAlreadyStartedError:
                            try:
                                execution = await app.state.temporal.get_workflow_handle(f"video-{record.id}").describe()
                                terminal_failures = {
                                    WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.CANCELED,
                                    WorkflowExecutionStatus.TERMINATED, WorkflowExecutionStatus.TIMED_OUT,
                                }
                                current = repo.get(record.id)
                                if execution.status in terminal_failures and current.status in {"queued", "running"}:
                                    repo.update(record.id, status="failed", stage="temporal",
                                                error=f"Temporal workflow ended: {execution.status.name}")
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                pass  # Reconcile status after the service reconnects.
                        except asyncio.CancelledError:
                            raise
                        except Exception:
                            # Keep it pending. The next dispatch or API restart
                            # retries the same workflow ID, never a new job.
                            continue
                    try:
                        await asyncio.wait_for(app.state.dispatch_wake.wait(), timeout=5)
                    except TimeoutError:
                        pass

            tasks.append(asyncio.create_task(dispatcher()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            if repository is None:
                repo.close()

    app = FastAPI(title="Vibe Knowledge Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    frontend = Path(settings.project_root) / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def frontend_page():
        index = frontend / "index.html"
        if not index.is_file():
            raise HTTPException(503, "Frontend is not built; run npm ci and npm run build in frontend/, then restart the server")
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/ui-config")
    async def ui_config():
        token = getattr(settings, "api_token", None)
        if hasattr(token, "get_secret_value"):
            token = token.get_secret_value()
        return {"requires_auth": bool(token)}

    def authorize(authorization: Annotated[str | None, Header()] = None):
        token = getattr(settings, "api_token", None)
        if hasattr(token, "get_secret_value"):
            token = token.get_secret_value()
        if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(401, "A valid bearer token is required", headers={"WWW-Authenticate": "Bearer"})

    protected = [Depends(authorize)]

    def find_job(request: Request, job_id: str) -> JobRecord:
        record = request.app.state.repository.get(job_id)
        if record is None:
            raise HTTPException(404, "Job not found")
        return record

    def artifact_path(job: JobRecord, raw_path: str) -> Path:
        root = Path(settings.output_dir).resolve()
        job_root = (root / job.id).resolve()
        path = Path(raw_path).resolve()
        if not job_root.is_relative_to(root) or not path.is_relative_to(job_root):
            raise HTTPException(404, "Artifact not found")
        if not path.is_file():
            raise HTTPException(404, "Artifact not found")
        return path

    @app.get("/health")
    async def health():
        return {"status": "ok", "execution_backend": getattr(settings, "execution_backend", "local")}

    @app.post("/jobs", status_code=202, response_model=JobRecord, dependencies=protected)
    async def submit(payload: JobCreate, request: Request):
        state = request.app.state
        async with state.admission_lock:
            if len(state.repository.pending()) >= int(getattr(settings, "max_queued_jobs", 100)):
                raise HTTPException(429, "Production queue is full; try again later", headers={"Retry-After": "30"})
            job = state.repository.create(payload)
            if state.backend == "local":
                state.queue.put_nowait(job.id)
            else:
                state.dispatch_wake.set()
        return job

    @app.get("/jobs", response_model=list[JobRecord], dependencies=protected)
    async def list_jobs(request: Request, limit: int = Query(50, ge=1, le=200)):
        return request.app.state.repository.list(limit)

    @app.get("/jobs/{job_id}", response_model=JobRecord, dependencies=protected)
    async def get_job(job_id: str, request: Request):
        return find_job(request, job_id)

    @app.post("/jobs/{job_id}/resume", status_code=202, response_model=JobRecord, dependencies=protected)
    async def resume_job(job_id: str, request: Request):
        state = request.app.state
        async with state.admission_lock:
            job = find_job(request, job_id)
            if getattr(job.status, "value", job.status) != "failed":
                raise HTTPException(409, "Only failed jobs can be resumed")
            if len(state.repository.pending()) >= int(getattr(settings, "max_queued_jobs", 100)):
                raise HTTPException(429, "Production queue is full; try again later", headers={"Retry-After": "30"})
            if state.backend == "temporal":
                from temporalio.client import WorkflowExecutionStatus

                # An activity can report failure while Temporal still owns an
                # automatic retry. Only explicitly restart a terminal workflow.
                try:
                    execution = await state.temporal.get_workflow_handle(f"video-{job.id}").describe()
                except Exception:
                    raise HTTPException(503, "Unable to confirm workflow state; try again later") from None
                if execution.status not in {
                    WorkflowExecutionStatus.FAILED, WorkflowExecutionStatus.CANCELED,
                    WorkflowExecutionStatus.TERMINATED, WorkflowExecutionStatus.TIMED_OUT,
                }:
                    raise HTTPException(409, "The workflow is still active or has already completed")
            job = state.repository.update(job.id, status="queued", stage="resuming", error=None)
            if state.backend == "local":
                state.queue.put_nowait(job.id)
            else:
                state.dispatch_wake.set()
        return job

    @app.get("/jobs/{job_id}/video", dependencies=protected)
    async def download_video(job_id: str, request: Request):
        job = find_job(request, job_id)
        if getattr(job.status, "value", job.status) != "succeeded" or not job.output_path:
            raise HTTPException(409, "Video is not ready")
        return FileResponse(artifact_path(job, job.output_path), media_type="video/mp4", filename="final.mp4")

    @app.get("/jobs/{job_id}/artifacts/{name:path}", dependencies=protected)
    async def download_artifact(job_id: str, name: str, request: Request):
        job = find_job(request, job_id)
        if name not in job.artifacts:
            raise HTTPException(404, "Artifact not found")
        path = artifact_path(job, job.artifacts[name])
        return FileResponse(path, filename=path.name)

    @app.get("/domains", dependencies=protected)
    async def domains():
        return [
            {"id": key, "name": label}
            for key, label in (
                ("mathematics", "数学"), ("history", "历史"), ("physics", "物理"),
                ("biology", "生物"), ("economics", "经济学"), ("literature", "文学"),
            )
        ]

    return app


app = create_app()
