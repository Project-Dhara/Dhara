"""PDF ingestion adapter — delegates to ``app.services.extraction.pdf.pipeline``."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

_PROGRESS = Optional[Callable[[str, int, str], None]]


def run_pdf_upload(
    file_path: Path,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    from app.services.extraction.pdf.pipeline import run_pdf_upload_pipeline

    return run_pdf_upload_pipeline(
        file_path, api_key=api_key, on_progress=on_progress
    )
