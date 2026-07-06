from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import BASE_DIR, CORS_ORIGINS
from app.routers import audits, documents, health, jobs, widgets, worksheets, workspace

app = FastAPI(
    title="CAM Reconciliation API",
    description=(
        "Backend for CAM (Common Area Maintenance) reconciliation audits. "
        "Upload lease and CAM statement PDFs, extract metrics via OpenAI, "
        "and run auditable cap/reconciliation calculations."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(audits.router)
app.include_router(documents.router)
app.include_router(worksheets.router)
app.include_router(widgets.router)
app.include_router(workspace.router)


@app.get("/sample.html")
async def serve_sample_html() -> FileResponse:
    sample_path = BASE_DIR / "sample.html"
    if not sample_path.exists():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="sample.html not found")
    return FileResponse(sample_path, media_type="text/html")
