from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.config import OPENAI_API_KEY
from app.models.schemas import JobCreateResponse, JobResponse, JobStatusEnum
from app.services.audit_pipeline import process_job
from app.services.files import save_pdf
from app.services.jobs import job_store

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _serialize_job(job) -> JobResponse:
    return JobResponse(
        job_id=job.job_id,
        status=JobStatusEnum(job.status),
        audit_id=job.audit_id,
        lease_filename=job.lease_filename,
        cam_filename=job.cam_filename,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        lease_prop_name=job.lease_prop_name,
        tenant_name=job.tenant_name,
        lease_id=job.lease_id,
    )


@router.get("", response_model=list[JobResponse])
async def list_jobs() -> list[JobResponse]:
    return [_serialize_job(job) for job in job_store.list_all()]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: UUID) -> JobResponse:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job)


@router.post("", response_model=JobCreateResponse)
async def create_job(
    background_tasks: BackgroundTasks,
    lease_pdf: UploadFile = File(...),
    cam_pdf: UploadFile = File(...),
    lease_prop_name: str = Form(""),
    tenant_name: str = Form(""),
    lease_id: str = Form(""),
) -> JobCreateResponse:
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    lease_bytes = await lease_pdf.read()
    cam_bytes = await cam_pdf.read()
    if not lease_bytes or not cam_bytes:
        raise HTTPException(status_code=400, detail="Both PDF files must be non-empty")

    lease_name = lease_pdf.filename or "lease.pdf"
    cam_name = cam_pdf.filename or "cam.pdf"
    job_dir = uuid4().hex

    lease_path = save_pdf(lease_bytes, lease_name, subdir=f"jobs/{job_dir}")
    cam_path = save_pdf(cam_bytes, cam_name, subdir=f"jobs/{job_dir}")

    job = job_store.create(
        lease_filename=lease_name,
        cam_filename=cam_name,
        lease_pdf_path=str(lease_path),
        cam_pdf_path=str(cam_path),
        lease_prop_name=lease_prop_name,
        tenant_name=tenant_name,
        lease_id=lease_id,
    )
    print(f"Created job {job}")

    background_tasks.add_task(process_job, job.job_id)
    return JobCreateResponse(
        job_id=job.job_id,
        status=JobStatusEnum.PENDING,
        lease_prop_name=job.lease_prop_name,
        tenant_name=job.tenant_name,
        lease_id=job.lease_id,
    )
