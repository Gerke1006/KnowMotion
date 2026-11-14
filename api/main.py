"""Run with ``uvicorn api.main:app --host 127.0.0.1 --port 8000``."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import json
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout

from api.configuration import ApiConfiguration, ConfigurationError, validate_changes
from api.media import register_media_routes
from api.production import register_production_routes
from api.job_process import ProcessCleanupError
from harness.schemas import JobCreate, JobRecord
from storage.repository import JobRepository
from harness.telemetry import JobTelemetry, enrich


def create_app(settings=None, *, repository=None, orchestrator_factory=None, api_settings_path=None) -> FastAPI:
    if settings is None:
        from harness.settings import Settings
        settings = Settings()
    configuration = ApiConfiguration(
        settings, Path(api_settings_path) if api_settings_path else Path(settings.project_root) / "data" / "runtime-api-settings.json",
    )
    public_mode = bool(getattr(settings, "public_mode", False))

    @asynccontextmanager
    async def runtime_lifespan(app: FastAPI):
        repo = repository or JobRepository(settings.database_url)
        factory = orchestrator_factory
        app.state.repository = repo
        app.state.queue = asyncio.Queue()
        app.state.admission_lock = asyncio.Lock()
        app.state.executions = {}
        backend = getattr(settings, "execution_backend", "local")
        if backend not in {"local", "temporal"}:
            raise RuntimeError("execution_backend must be local or temporal")
        app.state.backend = backend
        tasks = []
        if backend == "local":
            if factory is None:
                from api.job_process import recover_workers
                await recover_workers(settings.output_dir)
            # A single API process owns this development queue. For multi-process
            # or multi-host deployment use Temporal with a shared PostgreSQL DB.
            for record in repo.pending():
                if record.status == "cancelling":
                    finish_cancel(repo, record.id)
                    continue
                repo.update(record.id, status="queued", stage="resuming", error=None)
                app.state.queue.put_nowait(record.id)

            async def execute(snapshot, job_id):
                if factory is not None:
                    await factory(snapshot, repo).run(job_id)
                else:
                    from api.job_process import run_isolated
                    await run_isolated(snapshot, job_id)
                    record = repo.get(job_id)
                    if record.status in {"queued", "running"}:
                        repo.update(job_id, status="failed", stage="failed",
                                    error="Production process ended before completing the video.")

            async def worker():
                while True:
                    job_id = await app.state.queue.get()
                    execution = None
                    stopped = False
                    try:
                        record = repo.get(job_id)
                        if record is None or record.status in {"cancelled", "cancelling"}:
                            if record is not None and record.status == "cancelling":
                                finish_cancel(repo, job_id)
                            continue
                        # Each execution gets one immutable configuration snapshot.
                        # Saving settings cannot change a job already in progress.
                        snapshot = configuration.snapshot()
                        if public_mode:
                            validate_public_request(repo.get(job_id).request)
                            snapshot = snapshot.model_copy(update={"tts_enabled": True})
                        execution = asyncio.create_task(execute(snapshot, job_id))
                        app.state.executions[job_id] = execution
                        # Only the job child is cancelled by a stop request. The
                        # worker itself survives and can accept the next job.
                        await asyncio.shield(execution)
                        stopped = True
                    except asyncio.CancelledError:
                        stopping_server = bool(asyncio.current_task().cancelling())
                        if execution is not None:
                            if not execution.done():
                                execution.cancel()
                            try:
                                await execution
                            except asyncio.CancelledError:
                                pass
                            except ProcessCleanupError:
                                repo.update(job_id, _cleanup_failure=True, status="cancelling", stage="cancelling",
                                            error="Stopping production could not be confirmed; restart the service to reconcile workers.")
                                # Leave the slot closed. Shutdown interrupts this
                                # wait; startup reconciles the persisted PID tree.
                                if not stopping_server:
                                    await asyncio.Event().wait()
                                return
                        stopped = True
                        if repo.get(job_id).status == "cancelling":
                            finish_cancel(repo, job_id)
                        if stopping_server:
                            raise
                    except ProcessCleanupError:
                        repo.update(job_id, _cleanup_failure=True, status="cancelling", stage="cancelling",
                                    error="Stopping production could not be confirmed; restart the service to reconcile workers.")
                        await asyncio.Event().wait()
                    except Exception:
                        repo.update(job_id, status="failed", stage="failed", error="Video production failed; inspect worker logs and job artifacts.")
                    finally:
                        # This removal happens only after the process tree has
                        # stopped, including subprocess spawn/cancel races.
                        app.state.executions.pop(job_id, None)
                        current = repo.get(job_id)
                        if stopped and current is not None and current.status == "cancelling":
                            finish_cancel(repo, job_id)
                        app.state.queue.task_done()

            worker_count = 1 if public_mode else max(1, min(32, int(getattr(settings, "local_workers", 2))))
            for _ in range(worker_count):
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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Public deployments deliberately have one API owner and one worker.
        # A lifetime OS lock also rejects accidental --workers N / duplicate
        # containers sharing the output volume, so an asyncio admission lock
        # cannot silently become one independent lock per API process.
        owner = None
        if public_mode:
            if getattr(settings, "execution_backend", "local") != "local":
                raise RuntimeError("PUBLIC_MODE requires EXECUTION_BACKEND=local and one API process")
            root = Path(settings.output_dir).resolve()
            root.mkdir(parents=True, exist_ok=True)
            owner = FileLock(root / ".public-api-owner.lock")
            try:
                owner.acquire(timeout=0)
            except Timeout:
                raise RuntimeError("PUBLIC_MODE already has an API owner; run exactly one API process") from None
        try:
            async with runtime_lifespan(app):
                yield
        finally:
            if owner is not None:
                owner.release()

    app = FastAPI(title="Vibe Knowledge Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    frontend = Path(settings.project_root) / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/workspace", include_in_schema=False)
    @app.get("/workspace/", include_in_schema=False)
    async def frontend_page():
        index = frontend / "index.html"
        if not index.is_file():
            raise HTTPException(503, "Frontend is not built; run npm ci and npm run build in frontend/, then restart the server")
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/ui-config")
    async def ui_config(response: Response):
        response.headers["Cache-Control"] = "no-store"
        token = getattr(settings, "api_token", None)
        if hasattr(token, "get_secret_value"):
            token = token.get_secret_value()
        return {"requires_auth": bool(token) and not public_mode, "public_mode": public_mode,
                "can_edit_settings": not public_mode, "can_delete_jobs": not public_mode,
                "single_generation": public_mode,
                "can_cancel_jobs": getattr(settings, "execution_backend", "local") == "local"}

    def authorize(authorization: Annotated[str | None, Header()] = None):
        if public_mode:
            return
        token = getattr(settings, "api_token", None)
        if hasattr(token, "get_secret_value"):
            token = token.get_secret_value()
        if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(401, "A valid bearer token is required", headers={"WWW-Authenticate": "Bearer"})

    protected = [Depends(authorize)]

    def private_only():
        if public_mode:
            raise HTTPException(403, "This operation is disabled on the public website")

    private = [*protected, Depends(private_only)]

    @app.get("/settings/api", dependencies=private)
    async def get_api_settings(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return configuration.public()

    @app.put("/settings/api", dependencies=private)
    async def save_api_settings(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        if not configuration.editable:
            raise HTTPException(409, "Custom API settings require local execution; configure Temporal worker environments instead.")
        # Parse manually so FastAPI/Pydantic cannot echo secret input values in
        # validation errors. Neither request bodies nor keys are logged.
        try:
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 20000:
                    raise HTTPException(413, "API settings payload is too large")
                chunks.append(chunk)
            payload = json.loads(b"".join(chunks))
            changes = validate_changes(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(422, "API settings must be a valid JSON object") from None
        except ConfigurationError as exc:
            raise HTTPException(422, str(exc)) from None
        try:
            return configuration.save(changes)
        except OSError:
            raise HTTPException(503, "API settings could not be saved; check access to the local data directory") from None

    @app.delete("/settings/api", dependencies=private)
    async def reset_api_settings(response: Response):
        response.headers["Cache-Control"] = "no-store"
        if not configuration.editable:
            raise HTTPException(409, "Custom API settings require local execution; configure Temporal worker environments instead.")
        try:
            return configuration.reset()
        except OSError:
            raise HTTPException(503, "API settings could not be reset; check access to the local data directory") from None

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

    register_media_routes(app, settings, protected, find_job, artifact_path)
    register_production_routes(app, settings, protected, find_job, artifact_path)

    @app.get("/health")
    async def health():
        return {"status": "ok", "execution_backend": getattr(settings, "execution_backend", "local")}

    def visible_job(record):
        record = enrich(record, settings.output_dir)
        if not public_mode or record is None:
            return record
        # Public viewers get production progress and media routes, never server
        # paths or raw internal artifacts / exception details.
        return record.model_copy(update={
            "artifacts": {},
            "output_path": f"/jobs/{record.id}/video" if record.output_path else None,
            "error": "制作失败，请重新创建任务或稍后重试。" if record.error else None,
        })

    def active_jobs(state):
        pending = state.repository.pending()
        ids = {record.id for record in pending}
        # A worker can persist success just before its process finishes cleanup.
        return pending + [state.repository.get(job_id) for job_id in state.executions if job_id not in ids]

    def finish_cancel(repo, job_id):
        folder = Path(settings.output_dir) / job_id
        if folder.is_dir():
            JobTelemetry(repo, job_id, folder).finish_run("cancelled")
        return repo.update(job_id, status="cancelled", stage="cancelled", error=None, output_path=None)

    def require_capacity(state):
        pending = active_jobs(state)
        if public_mode and pending:
            raise HTTPException(409, {"code": "generation_busy", "message": "已有视频正在制作，请等待完成。",
                                      "active_job_id": pending[0].id}, headers={"Retry-After": "3"})
        if len(pending) >= int(getattr(settings, "max_queued_jobs", 100)):
            raise HTTPException(429, "Production queue is full; try again later", headers={"Retry-After": "30"})

    def validate_public_request(payload: JobCreate):
        if not public_mode:
            return
        if payload.mode != "live" or payload.tts_enabled is False:
            raise HTTPException(422, "Public video production requires live mode with narration")
        if (payload.width * payload.height > 1280 * 720 or payload.fps > 30 or payload.duration > 120
                or (payload.narration_char_budget or 0) > 600 or payload.renderer == "blender"):
            raise HTTPException(422, "Public video requests support up to 720p, 30 fps, 120 seconds and 600 narration characters")

    @app.get("/generation-state", dependencies=protected)
    async def generation_state(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        pending = active_jobs(request.app.state)
        return {"busy": bool(pending), "active_job": visible_job(pending[0]) if pending else None}

    @app.post("/jobs", status_code=202, response_model=JobRecord, dependencies=protected)
    async def submit(payload: JobCreate, request: Request):
        state = request.app.state
        async with state.admission_lock:
            require_capacity(state)
            validate_public_request(payload)
            job = state.repository.create(payload)
            if state.backend == "local":
                state.queue.put_nowait(job.id)
            else:
                state.dispatch_wake.set()
        return visible_job(job)

    @app.get("/jobs", response_model=list[JobRecord], dependencies=protected)
    async def list_jobs(request: Request, response: Response, limit: int = Query(50, ge=1, le=200)):
        response.headers["Cache-Control"] = "no-store"
        return [visible_job(record) for record in request.app.state.repository.list(limit)]

    @app.get("/jobs/{job_id}", response_model=JobRecord, dependencies=protected)
    async def get_job(job_id: str, request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return visible_job(find_job(request, job_id))

    @app.post("/jobs/{job_id}/cancel", status_code=202, response_model=JobRecord, dependencies=protected)
    async def cancel_job(job_id: str, request: Request):
        state = request.app.state
        if state.backend != "local":
            raise HTTPException(409, "Stopping jobs is available for the local execution backend")
        async with state.admission_lock:
            job = find_job(request, job_id)
            if job.status in {"cancelling", "cancelled"}:
                return visible_job(job)
            if job.status not in {"queued", "running"}:
                raise HTTPException(409, "Only queued or running jobs can be stopped")
            execution = state.executions.get(job_id)
            if job.status == "running" and execution is None:
                raise HTTPException(409, "This job is not owned by the website worker")
            job = state.repository.update(job_id, status="cancelling", stage="cancelling", error=None)
            if job.status != "cancelling":
                raise HTTPException(409, "The job has already finished")
            if execution is not None:
                execution.cancel()
            else:
                job = finish_cancel(state.repository, job_id)
        return visible_job(job)

    @app.delete("/jobs/{job_id}", status_code=204, dependencies=private)
    async def delete_job(job_id: str, request: Request):
        state = request.app.state
        async with state.admission_lock:
            job = find_job(request, job_id)
            if getattr(job.status, "value", job.status) not in {"succeeded", "failed", "cancelled"}:
                raise HTTPException(409, "Only completed or failed job records can be deleted")
            if job_id in state.executions:
                raise HTTPException(409, "Production cleanup is still active")
            if state.backend == "temporal":
                from temporalio.client import WorkflowExecutionStatus

                # A failed activity may still have a live workflow retry. Leave
                # its record intact until the workflow has actually settled.
                try:
                    execution = await state.temporal.get_workflow_handle(f"video-{job.id}").describe()
                except Exception:
                    raise HTTPException(503, "Unable to confirm workflow state; try again later") from None
                if execution.status not in {
                    WorkflowExecutionStatus.COMPLETED, WorkflowExecutionStatus.FAILED,
                    WorkflowExecutionStatus.CANCELED, WorkflowExecutionStatus.TERMINATED,
                    WorkflowExecutionStatus.TIMED_OUT,
                }:
                    raise HTTPException(409, "The workflow is still active")
            result = state.repository.delete_terminal(job.id)
            if result == "not_found":
                raise HTTPException(404, "Job not found")
            if result == "active":
                raise HTTPException(409, "The job is active and cannot be deleted")
        return Response(status_code=204)

    @app.post("/jobs/{job_id}/resume", status_code=202, response_model=JobRecord, dependencies=protected)
    async def resume_job(job_id: str, request: Request):
        state = request.app.state
        async with state.admission_lock:
            job = find_job(request, job_id)
            if getattr(job.status, "value", job.status) != "failed":
                raise HTTPException(409, "Only failed jobs can be resumed")
            require_capacity(state)
            validate_public_request(job.request)
            if public_mode and (Path(settings.output_dir) / job.id / "run_manifest.json").exists():
                raise HTTPException(409, "A failed frozen history run is closed; create a fresh job")
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
        return visible_job(job)

    @app.get("/jobs/{job_id}/video", dependencies=protected)
    async def download_video(job_id: str, request: Request):
        job = find_job(request, job_id)
        if getattr(job.status, "value", job.status) != "succeeded" or not job.output_path:
            raise HTTPException(409, "Video is not ready")
        return FileResponse(artifact_path(job, job.output_path), media_type="video/mp4", filename="final.mp4")

    @app.get("/jobs/{job_id}/artifacts/{name:path}", dependencies=private)
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
