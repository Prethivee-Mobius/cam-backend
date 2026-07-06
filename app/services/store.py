from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass
class AuditRecord:
    audit_id: UUID
    created_at: datetime
    updated_at: datetime
    status: str = "draft"
    key_metrics: list[dict[str, Any]] = field(default_factory=list)
    cam_line_items: list[dict[str, Any]] = field(default_factory=list)
    lease_operating_costs: dict[str, Any] = field(default_factory=dict)
    clauses: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    cam_comparison: list[dict[str, Any]] = field(default_factory=list)
    audit_control_metrics: list[dict[str, Any]] = field(default_factory=list)
    unified_audit_grid: list[dict[str, Any]] = field(default_factory=list)
    summary: list[dict[str, Any]] = field(default_factory=list)
    unified_grid: list[dict[str, Any]] = field(default_factory=list)
    cam_grid: list[dict[str, Any]] = field(default_factory=list)
    exceptions: list[dict[str, Any]] = field(default_factory=list)
    summary_cards: dict[str, Any] | None = None
    lease_filename: str = ""
    cam_filename: str = ""
    lease_pdf_path: str = ""
    cam_pdf_path: str = ""


class AuditStore:
    def __init__(self) -> None:
        self._audits: dict[UUID, AuditRecord] = {}

    def create(self, **kwargs: Any) -> AuditRecord:
        now = datetime.utcnow()
        record = AuditRecord(audit_id=uuid4(), created_at=now, updated_at=now, **kwargs)
        self._audits[record.audit_id] = record
        return record

    def get(self, audit_id: UUID) -> AuditRecord | None:
        return self._audits.get(audit_id)

    def update(self, audit_id: UUID, **kwargs: Any) -> AuditRecord | None:
        record = self._audits.get(audit_id)
        if not record:
            return None
        for key, value in kwargs.items():
            setattr(record, key, value)
        record.updated_at = datetime.utcnow()
        return record

    def list_all(self) -> list[AuditRecord]:
        return list(self._audits.values())


audit_store = AuditStore()
