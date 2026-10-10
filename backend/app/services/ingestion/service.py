"""Ingestion orchestration — upload step 1 (extract + validate).

Grouping and catalogue publishing are separate workflows (not invoked here).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from app.services.ingestion.contracts import SourceType

_PROGRESS = Optional[Callable[[str, int, str], None]]


def run_upload_pipeline(
    file_path: Path,
    source_type: SourceType,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    """Full upload job by ``source_type`` (step 1 only)."""
    file_path = Path(file_path)

    if source_type == "pdf":
        from app.services.ingestion.adapters.pdf import run_pdf_upload

        return run_pdf_upload(file_path, api_key=api_key, on_progress=on_progress)

    if source_type in ("excel", "csv"):
        from app.services.ingestion.adapters.excel import run_spreadsheet_upload

        return run_spreadsheet_upload(
            file_path,
            source_type,
            api_key=api_key,
            on_progress=on_progress,
        )

    raise ValueError(f"Unknown source_type: {source_type}")


# Alias used by workers / callers
run_upload_job = run_upload_pipeline
