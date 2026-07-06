from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.config import OPENAI_API_KEY
from app.models.schemas import (
    AuditControlMetricRow,
    AuditDetailResponse,
    AuditMetrics,
    AuditStatus,
    CalculateRequest,
    CalculateResponse,
    CamLineItem,
    CamTableItem,
    Clause,
    ExtractResponse,
    HealthResponse,
    KeyMetric,
    LeaseOperatingCosts,
    UnifiedAuditGridRow,
)
from app.services.audit_pipeline import create_audit_from_files
from app.services.export import build_unified_audit_grid_excel
from app.services.recalculate import recalculate_worksheets
from app.services.store import audit_store
from app.services.worksheets import build_audit_control_metrics

router = APIRouter(prefix="/api/v1/audits", tags=["audits"])


def _serialize_audit(record) -> AuditDetailResponse:
    return AuditDetailResponse(
        audit_id=record.audit_id,
        status=AuditStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        key_metrics=[KeyMetric(**m) for m in record.key_metrics],
        cam_line_items=[CamLineItem(**item) for item in record.cam_line_items],
        lease_operating_costs=LeaseOperatingCosts(**record.lease_operating_costs),
        clauses=[Clause(**c) for c in record.clauses],
        metrics=AuditMetrics(**record.metrics),
        audit_control_metrics=[AuditControlMetricRow(**row) for row in record.audit_control_metrics],
        unified_audit_grid=[UnifiedAuditGridRow(**row) for row in record.unified_audit_grid],
        summary=record.summary,
        unified_grid=record.unified_grid,
        cam_grid=record.cam_grid,
        exceptions=record.exceptions,
        summary_cards=record.summary_cards,
    )


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", openai_configured=bool(OPENAI_API_KEY))


@router.post("/extract", response_model=ExtractResponse)
async def extract_audit_documents(
    lease_pdf: UploadFile = File(..., description="Lease PDF document"),
    cam_pdf: UploadFile = File(..., description="CAM reconciliation PDF document"),
) -> ExtractResponse:
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    if lease_pdf.content_type not in ("application/pdf", "application/octet-stream", None):
        raise HTTPException(status_code=400, detail="lease_pdf must be a PDF file")
    if cam_pdf.content_type not in ("application/pdf", "application/octet-stream", None):
        raise HTTPException(status_code=400, detail="cam_pdf must be a PDF file")

    lease_bytes = await lease_pdf.read()
    cam_bytes = await cam_pdf.read()

    if not lease_bytes or not cam_bytes:
        raise HTTPException(status_code=400, detail="Both PDF files must be non-empty")

    try:
        record = create_audit_from_files(
            lease_bytes,
            lease_pdf.filename or "lease.pdf",
            cam_bytes,
            cam_pdf.filename or "cam.pdf",
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Document extraction failed: {exc}") from exc

    return ExtractResponse(
        audit_id=record.audit_id,
        key_metrics=[KeyMetric(**m) for m in record.key_metrics],
        cam_line_items=[CamLineItem(**item) for item in record.cam_line_items],
        lease_operating_costs=LeaseOperatingCosts(**record.lease_operating_costs),
        clauses=[Clause(**c) for c in record.clauses],
        metrics=AuditMetrics(**record.metrics),
        status=AuditStatus.DRAFT,
    )


@router.post("/{audit_id}/calculate", response_model=CalculateResponse)
async def calculate_audit(audit_id: UUID, payload: CalculateRequest) -> CalculateResponse:
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")

    cam_items = (
        [item.model_dump(by_alias=True) for item in payload.cam_line_items]
        if payload.cam_line_items is not None
        else None
    )
    control_rows = None
    if payload.audit_control_metrics is not None:
        control_rows = [row.model_dump() for row in payload.audit_control_metrics]
    elif payload.metrics is not None:
        control_rows = build_audit_control_metrics(payload.metrics)

    if cam_items is None and control_rows is None:
        raise HTTPException(
            status_code=400,
            detail="Provide cam_line_items, audit_control_metrics, and/or metrics",
        )

    try:
        calc = recalculate_worksheets(
            audit_id,
            cam_line_items=cam_items,
            audit_control_metrics=control_rows,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    record = audit_store.get(audit_id)
    return CalculateResponse(
        audit_id=audit_id,
        cam_line_items=[CamLineItem(**item) for item in record.cam_line_items],
        audit_control_metrics=[AuditControlMetricRow(**row) for row in record.audit_control_metrics],
        unified_audit_grid=[UnifiedAuditGridRow(**row) for row in calc["unified_audit_grid"]],
        summary=calc["summary"],
        exceptions=calc["exceptions"],
        summary_cards=calc["summary_cards"],
    )


@router.get("/{audit_id}", response_model=AuditDetailResponse)
async def get_audit(audit_id: UUID) -> AuditDetailResponse:
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _serialize_audit(record)


@router.get("/{audit_id}/lease-operating-costs", response_model=LeaseOperatingCosts)
async def get_lease_operating_costs(audit_id: UUID) -> LeaseOperatingCosts:
    """Return lease included/excluded operating costs with pdfCoordinates."""
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")
    return LeaseOperatingCosts(**record.lease_operating_costs)


@router.get("/{audit_id}/cam-line-items", response_model=list[CamTableItem])
async def get_cam_line_items(audit_id: UUID) -> list[CamTableItem]:
    """Return CAM table line items with pdfCoordinates."""
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")
    return [
        CamTableItem(
            Category=item.get("Category", ""),
            Amount=float(item.get("Amount", 0.0) or 0.0),
            value=item.get("value"),
            page_number=item.get("page_number"),
            pdfCoordinates=item.get("pdfCoordinates"),
        )
        for item in record.cam_line_items
    ]


def _pdf_file_response(record, path_attr: str, filename_attr: str, label: str) -> FileResponse:
    pdf_path = Path(getattr(record, path_attr) or "")
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail=f"{label} PDF not found for this audit")
    filename = getattr(record, filename_attr) or pdf_path.name
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)


@router.get("/{audit_id}/documents/lease")
async def get_lease_document(audit_id: UUID) -> FileResponse:
    """Stream the stored lease PDF for in-app viewing."""
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _pdf_file_response(record, "lease_pdf_path", "lease_filename", "Lease")


@router.get("/{audit_id}/documents/cam")
async def get_cam_document(audit_id: UUID) -> FileResponse:
    """Stream the stored CAM statement PDF for in-app viewing."""
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")
    return _pdf_file_response(record, "cam_pdf_path", "cam_filename", "CAM")


@router.get("/{audit_id}/export")
async def export_audit(audit_id: UUID) -> Response:
    """Download Unified CAM Audit Grid as Excel (same as worksheets export)."""
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")

    if not record.unified_audit_grid:
        recalculate_worksheets(audit_id)
        record = audit_store.get(audit_id)

    workbook = build_unified_audit_grid_excel(record.unified_audit_grid)

    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="Unified_CAM_Audit_Grid_{audit_id}.xlsx"'
        },
    )


@router.patch("/{audit_id}/status")
async def update_audit_status(audit_id: UUID, status: AuditStatus) -> dict:
    record = audit_store.get(audit_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit not found")

    if status == AuditStatus.APPROVED:
        open_exceptions = [e for e in record.exceptions if e.get("status") == "open"]
        if open_exceptions:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve audit with {len(open_exceptions)} open exception(s)",
            )

    audit_store.update(audit_id, status=status.value)
    return {"audit_id": str(audit_id), "status": status.value}
