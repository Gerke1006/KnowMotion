"""SQLite for local development; the same schema works with PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
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
            values = conn.execute(select(self.jobs.c.payload).where(self.jobs.c.status.in_(["queued", "running"])).order_by(self.jobs.c.created_at)).scalars().all()
        return [JobRecord.model_validate_json(value) for value in values]

    def update(self, job_id: str, **fields) -> JobRecord:
        if {"id", "created_at", "request", "topic", "mode"}.intersection(fields):
            raise ValueError("Job identity and request cannot be changed")
        with self.lock, self.engine.begin() as conn:
            row = conn.execute(select(self.jobs.c.payload).where(self.jobs.c.id == job_id).with_for_update()).scalar_one_or_none()
            if row is None:
                raise KeyError(job_id)
            data = JobRecord.model_validate_json(row).model_dump()
            data.update(fields, updated_at=datetime.now(timezone.utc).isoformat())
            updated = JobRecord.model_validate(data)
            conn.execute(self.jobs.update().where(self.jobs.c.id == job_id).values(
                status=self._status(updated), payload=updated.model_dump_json(),
            ))
        return updated

    def close(self) -> None:
        self.engine.dispose()
