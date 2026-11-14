"""SQLite for local development; the same schema works with PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.pool import StaticPool

from harness.schemas import JobCreate, JobRecord


class JobRepository:
    def __init__(self, database_url: str):
        options = {}
        if database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if database_url in {"sqlite://", "sqlite:///:memory:"}:
                options["poolclass"] = StaticPool
            elif database_url.startswith("sqlite:///"):
                Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, pool_pre_ping=True, **options)
        self.lock = RLock()
        metadata = MetaData()
        self.jobs = Table(
            "video_jobs", metadata,
            Column("id", String(36), primary_key=True),
            Column("status", String(16), nullable=False, index=True),
            Column("created_at", String(40), nullable=False, index=True),
            Column("payload", Text, nullable=False),
        )
        metadata.create_all(self.engine)

    @staticmethod
    def _status(record: JobRecord) -> str:
        return getattr(record.status, "value", record.status)

    def create(self, request: JobCreate) -> JobRecord:
        now = datetime.now(timezone.utc).isoformat()
        record = JobRecord(
            id=str(uuid4()), topic=request.topic, mode=request.mode,
            request=request, status="queued", stage="queued", progress=0,
            created_at=now, updated_at=now, artifacts={},
        )
        with self.lock, self.engine.begin() as conn:
            conn.execute(self.jobs.insert().values(
                id=record.id, status=self._status(record), created_at=now,
                payload=record.model_dump_json(),
            ))
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self.lock, self.engine.connect() as conn:
            value = conn.execute(select(self.jobs.c.payload).where(self.jobs.c.id == job_id)).scalar_one_or_none()
        return None if value is None else JobRecord.model_validate_json(value)

    def list(self, limit: int = 50) -> list[JobRecord]:
        with self.lock, self.engine.connect() as conn:
            values = conn.execute(select(self.jobs.c.payload).order_by(self.jobs.c.created_at.desc()).limit(limit)).scalars().all()
        return [JobRecord.model_validate_json(value) for value in values]

    def pending(self) -> list[JobRecord]:
        with self.lock, self.engine.connect() as conn:
            values = conn.execute(select(self.jobs.c.payload).where(self.jobs.c.status.in_(["queued", "running", "cancelling"])).order_by(self.jobs.c.created_at)).scalars().all()
        return [JobRecord.model_validate_json(value) for value in values]

    def update(self, job_id: str, *, _cleanup_failure=False, **fields) -> JobRecord:
        if {"id", "created_at", "request", "topic", "mode"}.intersection(fields):
            raise ValueError("Job identity and request cannot be changed")
        # The API and isolated production process can write the same row. Compare
        # the payload on UPDATE so a late stage/heartbeat cannot overwrite stop.
        with self.lock:
            for _ in range(20):
                with self.engine.begin() as conn:
                    row = conn.execute(select(self.jobs.c.payload).where(self.jobs.c.id == job_id).with_for_update()).scalar_one_or_none()
                    if row is None:
                        raise KeyError(job_id)
                    current = JobRecord.model_validate_json(row)
                    status = self._status(current)
                    requested = getattr(fields.get("status"), "value", fields.get("status"))
                    if requested == "cancelling" and not _cleanup_failure and status not in {"queued", "running", "cancelling"}:
                        return current
                    if status in {"cancelling", "cancelled"}:
                        allowed = (status == "cancelling" and requested == "cancelled") or set(fields) <= {"telemetry"}
                        if not allowed:
                            return current
                    data = current.model_dump()
                    data.update(fields, updated_at=datetime.now(timezone.utc).isoformat())
                    updated = JobRecord.model_validate(data)
                    result = conn.execute(self.jobs.update().where(
                        self.jobs.c.id == job_id, self.jobs.c.payload == row,
                    ).values(status=self._status(updated), payload=updated.model_dump_json()))
                    if result.rowcount:
                        return updated
        raise RuntimeError("Concurrent job updates could not be reconciled")

    def close(self) -> None:
        self.engine.dispose()

    def delete_terminal(self, job_id: str) -> Literal["deleted", "not_found", "active"]:
        """Remove only a settled record; production files are intentionally retained.

        The status predicate is part of the DELETE itself so an update/resume in
        another worker cannot turn an earlier read into deletion of an active job.
        """
        with self.lock, self.engine.begin() as conn:
            result = conn.execute(self.jobs.delete().where(
                self.jobs.c.id == job_id,
                self.jobs.c.status.in_(["succeeded", "failed", "cancelled"]),
            ))
            if result.rowcount:
                return "deleted"
            status = conn.execute(select(self.jobs.c.status).where(self.jobs.c.id == job_id)).scalar_one_or_none()
            return "not_found" if status is None else "active"
