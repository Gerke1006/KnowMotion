"""Start a worker with ``python -m workflows.worker`` (install temporal extra)."""

from __future__ import annotations

import asyncio
from contextlib import suppress


async def main():
    from temporalio import activity
    from temporalio.client import Client
    from temporalio.exceptions import ApplicationError
    from temporalio.worker import Worker

    from harness.orchestrator import Orchestrator
    from harness.settings import Settings
    from storage.repository import JobRepository
    from workflows.temporal import VideoProductionWorkflow

    settings = Settings()
    repository = JobRepository(settings.database_url)

    @activity.defn(name="produce_video")
    async def produce_video(job_id: str) -> dict:
        async def heartbeat():
            while True:
                activity.heartbeat(job_id)
                await asyncio.sleep(20)

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            result = await Orchestrator(settings, repository).run(job_id)
            if getattr(result.status, "value", result.status) == "failed":
                raise ApplicationError("Video production failed; inspect job status", type="ProductionError")
            return {"job_id": result.id, "status": getattr(result.status, "value", result.status)}
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task

    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    try:
        async with Worker(
            client, task_queue=settings.temporal_task_queue,
            workflows=[VideoProductionWorkflow], activities=[produce_video],
            max_concurrent_activities=max(1, settings.local_workers),
        ):
            await asyncio.Future()
    finally:
        repository.close()


if __name__ == "__main__":
    asyncio.run(main())
