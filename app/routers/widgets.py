from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.models.schemas import AuditWidgetsResponse
from app.services.recalculate import recalculate_worksheets
from app.services.store import audit_store
from app.services.widgets import build_audit_widgets
from app.models.schemas import AuditMetrics
from app.services.worksheets import ensure_control_metric_rows

router = APIRouter(prefix="/api/v1/audits", tags=["widgets"])


@router.get("/{audit_id}/widgets", response_model=AuditWidgetsResponse)
async def get_audit_widgets(audit_id: UUID) -> AuditWidgetsResponse:
    """Return the six audit summary widgets for dashboard display."""
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")

    if not record.summary_cards or not record.unified_audit_grid:
        try:
            recalculate_worksheets(audit_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        record = audit_store.get(audit_id)
        if not record:
            raise HTTPException(status_code=404, detail="Audit not found")

    metrics = AuditMetrics(**record.metrics)
    control_rows = ensure_control_metric_rows(record.audit_control_metrics or [], metrics)

    return build_audit_widgets(
        audit_id,
        cam_line_items=record.cam_line_items,
        summary_cards=record.summary_cards,
        audit_control_metrics=control_rows,
        summary=record.summary or [],
        updated_at=record.updated_at,
    )
