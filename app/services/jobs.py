from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobRecord:
    job_id: UUID
    created_at: datetime
    updated_at: datetime
    status: str = JobStatus.PENDING.value
    audit_id: UUID | None = None
    lease_filename: str = ""
    cam_filename: str = ""
    lease_pdf_path: str = ""
    cam_pdf_path: str = ""
    error: str | None = None
    lease_prop_name: str = ""
    tenant_name: str = ""
    lease_id: str = ""


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[UUID, JobRecord] = {}

    def create(self, **kwargs: Any) -> JobRecord:
        now = datetime.utcnow()
        record = JobRecord(job_id=uuid4(), created_at=now, updated_at=now, **kwargs)
        self._jobs[record.job_id] = record
        return record

    def get(self, job_id: UUID) -> JobRecord | None:
        return self._jobs.get(job_id)

    def update(self, job_id: UUID, **kwargs: Any) -> JobRecord | None:
        record = self._jobs.get(job_id)
        if not record:
            return None
        for key, value in kwargs.items():
            setattr(record, key, value)
        record.updated_at = datetime.utcnow()
        return record

    def list_all(self) -> list[JobRecord]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)


job_store = JobStore()
