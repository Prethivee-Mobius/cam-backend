from pathlib import Path

from fastapi import APIRouter

from app.config import OPENAI_API_KEY
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", openai_configured=bool(OPENAI_API_KEY))


@router.get("/")
async def root() -> dict:
    return {
        "name": "CAM Reconciliation API",
        "version": "1.0.0",
        "docs": "/docs",
        "sample_frontend": "/sample.html",
    }
