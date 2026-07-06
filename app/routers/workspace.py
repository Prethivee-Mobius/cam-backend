from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.services.recalculate import recalculate_worksheets
from app.services.store import audit_store

router = APIRouter(prefix="/api/v1/audits", tags=["workspace"])


def _to_camel_exception(exc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": exc["id"],
        "rowId": exc.get("row_id"),
        "category": exc["category"],
        "severity": exc["severity"],
        "issue": exc["issue"],
        "variance": exc["variance"],
        "clauseRef": exc.get("clause_ref"),
        "recommendation": exc["recommendation"],
        "status": exc.get("status", "open"),
    }


@router.get("/{audit_id}/workspace")
async def get_audit_workspace(audit_id: UUID) -> dict[str, Any]:
    """Return audit data shaped for the sample.html audit workspace UI."""
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")

    if not record.unified_audit_grid:
        recalculate_worksheets(audit_id)
        record = audit_store.get(audit_id)

    cards = record.summary_cards or {}
    return {
        "auditId": str(record.audit_id),
        "status": record.status,
        "leaseFilename": record.lease_filename,
        "camFilename": record.cam_filename,
        "clauses": record.clauses,
        "worksheets": {
            "camLineItems": record.cam_line_items,
            "auditControlMetrics": record.audit_control_metrics,
            "unifiedAuditGrid": record.unified_audit_grid,
        },
        "exceptions": [_to_camel_exception(e) for e in record.exceptions],
        "summaryCards": {
            "totalCurrentCam": cards.get("total_current_cam", 0),
            "totalAllowableCam": cards.get("total_allowable_cam", 0),
            "totalVariance": cards.get("total_variance", 0),
            "exceptionCount": cards.get("exception_count", 0),
            "openExceptionCount": cards.get("open_exception_count", 0),
            "highSeverityCount": cards.get("high_severity_count", 0),
            "auditCompletionPct": cards.get("audit_completion_pct", 0),
        },
        "metrics": record.metrics,
        "summary": record.summary,
    }
