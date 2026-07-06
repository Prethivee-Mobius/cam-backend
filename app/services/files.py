from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.config import UPLOAD_DIR


def save_pdf(content: bytes, filename: str, subdir: str | None = None) -> Path:
    folder = UPLOAD_DIR / (subdir or uuid4().hex)
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "document.pdf"
    path = folder / safe_name
    path.write_bytes(content)
    return path
