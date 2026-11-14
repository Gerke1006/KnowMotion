"""Temporal durable dispatch; activities resume existing stage artifacts."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class VideoProductionWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        return await workflow.execute_activity(
            "produce_video", job_id,
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=3,
                non_retryable_error_types=["ValueError", "ValidationError", "ConfigurationError"],
            ),
        )
