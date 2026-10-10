"""
Upload pipeline orchestration.

- **Step 1:** ``data_ingestion`` → extract + validate (PDF, Excel, CSV).
  PDF details: ``data_ingestion/pdf/README.md``.
- **Step 2+:** grouping and catalogue (PDF jobs / batch-extract), not here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from data_ingestion.pdf.pipeline import run_pdf_upload_pipeline
from data_ingestion.spreadsheet_pipeline import run_spreadsheet_upload_pipeline
from data_ingestion.utils.types import SourceType

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
        return run_pdf_upload_pipeline(
            file_path, api_key=api_key, on_progress=on_progress
        )

    if source_type in ("excel", "csv"):
        return run_spreadsheet_upload_pipeline(
            file_path,
            source_type,
            api_key=api_key,
            on_progress=on_progress,
        )

    raise ValueError(f"Unknown source_type: {source_type}")
