from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import OPENAI_API_KEY
from app.models.schemas import CamTableItem, LeaseOperatingCosts
from app.services.extraction import extract_cam_only, extract_lease_only
from app.services.store import audit_store

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def _validate_pdf(upload: UploadFile, field_name: str) -> None:
    if upload.content_type not in ("application/pdf", "application/octet-stream", None):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a PDF file")


def _cam_table_response(items: list[dict]) -> list[CamTableItem]:
    return [
        CamTableItem(
            Category=item.get("Category", ""),
            Amount=float(item.get("Amount", 0.0) or 0.0),
            value=item.get("value"),
            page_number=item.get("page_number"),
            pdfCoordinates=item.get("pdfCoordinates"),
        )
        for item in items
    ]


@router.post("/lease/operating-costs", response_model=LeaseOperatingCosts)
async def extract_lease_operating_costs_document(
    lease_pdf: UploadFile = File(..., description="Lease PDF document"),
) -> LeaseOperatingCosts:
    """Extract included/excluded lease operating costs with PDF coordinates."""
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    _validate_pdf(lease_pdf, "lease_pdf")
    lease_bytes = await lease_pdf.read()
    if not lease_bytes:
        raise HTTPException(status_code=400, detail="lease_pdf must be non-empty")

    try:
        extracted = extract_lease_only(lease_bytes, lease_pdf.filename or "lease.pdf")
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lease extraction failed: {exc}") from exc

    return LeaseOperatingCosts(**extracted["lease_operating_costs"])


@router.post("/cam/table", response_model=list[CamTableItem])
async def extract_cam_table_document(
    cam_pdf: UploadFile = File(..., description="CAM reconciliation PDF document"),
) -> list[CamTableItem]:
    """Extract CAM cost line items with PDF coordinates."""
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    _validate_pdf(cam_pdf, "cam_pdf")
    cam_bytes = await cam_pdf.read()
    if not cam_bytes:
        raise HTTPException(status_code=400, detail="cam_pdf must be non-empty")

    try:
        extracted = extract_cam_only(cam_bytes, cam_pdf.filename or "cam.pdf")
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"CAM extraction failed: {exc}") from exc

    return _cam_table_response(extracted["cam_line_items"])
