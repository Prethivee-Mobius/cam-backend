from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.config import OPENAI_API_KEY
from app.services.extraction import extract_documents
from app.services.jobs import JobStatus, job_store
from app.services.recalculate import recalculate_worksheets
from app.services.store import audit_store


def create_audit_from_files(
    lease_bytes: bytes,
    lease_filename: str,
    cam_bytes: bytes,
    cam_filename: str,
):
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not configured")

    extracted = extract_documents(lease_bytes, lease_filename, cam_bytes, cam_filename)
    record = audit_store.create(
        key_metrics=extracted["key_metrics"],
        cam_line_items=extracted["cam_line_items"],
        lease_operating_costs=extracted["lease_operating_costs"],
        clauses=extracted["clauses"],
        metrics=extracted["metrics"],
        lease_filename=lease_filename,
        cam_filename=cam_filename,
        lease_pdf_path=extracted.get("lease_pdf_path", ""),
        cam_pdf_path=extracted.get("cam_pdf_path", ""),
        cam_comparison=extracted.get("cam_comparison") or [],
    )
    recalculate_worksheets(record.audit_id)
    return record


def process_job(job_id: UUID) -> None:
    job = job_store.get(job_id)
    if not job:
        return

    job_store.update(job_id, status=JobStatus.RUNNING.value)

    try:
        lease_path = Path(job.lease_pdf_path)
        cam_path = Path(job.cam_pdf_path)
        record = create_audit_from_files(
            lease_path.read_bytes(),
            job.lease_filename or lease_path.name,
            cam_path.read_bytes(),
            job.cam_filename or cam_path.name,
        )
        job_store.update(
            job_id,
            status=JobStatus.COMPLETED.value,
            audit_id=record.audit_id,
            error=None,
        )
    except Exception as exc:
        job_store.update(job_id, status=JobStatus.FAILED.value, error=str(exc))
