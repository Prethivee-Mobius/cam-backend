from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.models.schemas import (
    AuditControlMetricRow,
    AuditControlMetricsResponse,
    AuditControlMetricsUpdateRequest,
    AuditMetrics,
    CamLineItem,
    CamLineItemsLedgerResponse,
    CamLineItemsUpdateRequest,
    ConsolidatedSummaryResponse,
    SummaryRow,
    UnifiedAuditGridResponse,
    UnifiedAuditGridReviewUpdateRequest,
    UnifiedAuditGridRow,
    WorksheetsResponse,
    WorksheetsUpdateRequest,
)
from app.services.export import build_unified_audit_grid_excel
from app.services.recalculate import recalculate_worksheets, save_unified_grid_reviewer_comments
from app.services.store import audit_store
from app.services.worksheets import ensure_control_metric_rows

router = APIRouter(prefix="/api/v1/audits", tags=["worksheets"])


def _get_record(audit_id: UUID):
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")
    return record


def _unified_rows(rows: list[dict]) -> list[UnifiedAuditGridRow]:
    return [UnifiedAuditGridRow(**row) for row in rows]


def _summary_rows(rows: list[dict]) -> list[SummaryRow]:
    return [SummaryRow(**row) for row in rows]


def _worksheets_response(audit_id: UUID) -> WorksheetsResponse:
    record = _get_record(audit_id)
    metrics = AuditMetrics(**record.metrics)
    control_rows = ensure_control_metric_rows(record.audit_control_metrics or [], metrics)
    return WorksheetsResponse(
        audit_id=audit_id,
        cam_line_items=[CamLineItem(**item) for item in record.cam_line_items],
        audit_control_metrics=[AuditControlMetricRow(**row) for row in control_rows],
        unified_audit_grid=_unified_rows(record.unified_audit_grid),
        consolidated_summary=_summary_rows(record.summary or []),
    )


def _run_recalc(
    audit_id: UUID,
    *,
    cam_line_items: list[dict] | None = None,
    audit_control_metrics: list[dict] | None = None,
) -> WorksheetsResponse:
    try:
        recalculate_worksheets(
            audit_id,
            cam_line_items=cam_line_items,
            audit_control_metrics=audit_control_metrics,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _worksheets_response(audit_id)


@router.get("/{audit_id}/worksheets", response_model=WorksheetsResponse)
async def get_all_worksheets(audit_id: UUID) -> WorksheetsResponse:
    """Return all three worksheet tabs in one payload."""
    record = _get_record(audit_id)
    if not record.unified_audit_grid:
        return _run_recalc(audit_id)
    return _worksheets_response(audit_id)


@router.put("/{audit_id}/worksheets", response_model=WorksheetsResponse)
async def update_worksheets(audit_id: UUID, payload: WorksheetsUpdateRequest) -> WorksheetsResponse:
    """Update tab 1 and/or tab 2; tab 3 is recalculated automatically."""
    _get_record(audit_id)

    if payload.cam_line_items is None and payload.audit_control_metrics is None:
        raise HTTPException(status_code=400, detail="Provide cam_line_items and/or audit_control_metrics")

    cam_items = (
        [item.model_dump(by_alias=True) for item in payload.cam_line_items]
        if payload.cam_line_items is not None
        else None
    )
    control_rows = (
        [row.model_dump() for row in payload.audit_control_metrics]
        if payload.audit_control_metrics is not None
        else None
    )
    return _run_recalc(audit_id, cam_line_items=cam_items, audit_control_metrics=control_rows)


@router.put("/{audit_id}/worksheets/cam-line-items", response_model=WorksheetsResponse)
async def update_cam_line_items_ledger(
    audit_id: UUID,
    payload: CamLineItemsUpdateRequest,
) -> WorksheetsResponse:
    """Edit tab 1 (CAM Line Items Expense Ledger) and recalculate tab 3."""
    _get_record(audit_id)
    cam_items = [item.model_dump(by_alias=True) for item in payload.rows]
    return _run_recalc(audit_id, cam_line_items=cam_items)


@router.put("/{audit_id}/worksheets/audit-control-metrics", response_model=WorksheetsResponse)
async def update_audit_control_metrics_tab(
    audit_id: UUID,
    payload: AuditControlMetricsUpdateRequest,
) -> WorksheetsResponse:
    """Edit tab 2 (Audit Control Metrics) and recalculate tab 3."""
    _get_record(audit_id)
    control_rows = [row.model_dump() for row in payload.rows]
    return _run_recalc(audit_id, audit_control_metrics=control_rows)


@router.get("/{audit_id}/worksheets/cam-line-items", response_model=CamLineItemsLedgerResponse)
async def get_cam_line_items_ledger(audit_id: UUID) -> CamLineItemsLedgerResponse:
    """Tab 1: CAM Line Items Expense Ledger."""
    record = _get_record(audit_id)
    if not record.unified_audit_grid:
        _run_recalc(audit_id)
        record = _get_record(audit_id)
    return CamLineItemsLedgerResponse(
        audit_id=audit_id,
        rows=[CamLineItem(**item) for item in record.cam_line_items],
    )


@router.get("/{audit_id}/worksheets/audit-control-metrics", response_model=AuditControlMetricsResponse)
async def get_audit_control_metrics(audit_id: UUID) -> AuditControlMetricsResponse:
    """Tab 2: Audit Control Metrics."""
    record = _get_record(audit_id)
    if not record.unified_audit_grid:
        _run_recalc(audit_id)
        record = _get_record(audit_id)
    return AuditControlMetricsResponse(
        audit_id=audit_id,
        rows=[AuditControlMetricRow(**row) for row in record.audit_control_metrics],
    )


@router.get("/{audit_id}/worksheets/unified-audit-grid", response_model=UnifiedAuditGridResponse)
async def get_unified_audit_grid(audit_id: UUID) -> UnifiedAuditGridResponse:
    """Tab 3: Unified CAM Audit Grid (read-only calculated output)."""
    record = _get_record(audit_id)
    if not record.unified_audit_grid:
        _run_recalc(audit_id)
        record = _get_record(audit_id)
    return UnifiedAuditGridResponse(
        audit_id=audit_id,
        rows=_unified_rows(record.unified_audit_grid),
    )


@router.get("/{audit_id}/worksheets/consolidated-summary", response_model=ConsolidatedSummaryResponse)
async def get_consolidated_summary(audit_id: UUID) -> ConsolidatedSummaryResponse:
    """Consolidated Reconciliation Worksheet (Streamlit section 3)."""
    record = _get_record(audit_id)
    if not record.unified_audit_grid:
        _run_recalc(audit_id)
        record = _get_record(audit_id)
    return ConsolidatedSummaryResponse(
        audit_id=audit_id,
        rows=_summary_rows(record.summary or []),
    )


@router.put("/{audit_id}/worksheets/unified-audit-grid", response_model=UnifiedAuditGridResponse)
async def update_unified_audit_grid_reviewer_comments(
    audit_id: UUID,
    payload: UnifiedAuditGridReviewUpdateRequest,
) -> UnifiedAuditGridResponse:
    """Save reviewer comments on tab 3 (Status is read-only and derived from variance)."""
    _get_record(audit_id)
    updates = [row.model_dump(by_alias=True) for row in payload.rows]
    try:
        grid = save_unified_grid_reviewer_comments(audit_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return UnifiedAuditGridResponse(
        audit_id=audit_id,
        rows=_unified_rows(grid),
    )


@router.get("/{audit_id}/worksheets/unified-audit-grid/export")
async def export_unified_audit_grid(audit_id: UUID) -> Response:
    """Download the Unified CAM Audit Grid as Excel."""
    record = _get_record(audit_id)
    if not record.unified_audit_grid:
        _run_recalc(audit_id)
        record = _get_record(audit_id)

    workbook = build_unified_audit_grid_excel(record.unified_audit_grid)
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="Unified_CAM_Audit_Grid_{audit_id}.xlsx"'
        },
    )
