"""
Upload pipeline orchestration.

- **Spreadsheet** (excel / csv): ``spreadsheet_pipeline`` → ``PreValidationInput`` → validation.
- **PDF**: unchanged — PyMuPDF in ``extraction`` then validation (no ``PreValidationInput`` yet).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from data_ingestion.pdf import prepare_pdf_source
from data_ingestion.spreadsheet_pipeline import run_spreadsheet_upload_pipeline
from data_ingestion.utils.enrich import tag_tables_with_source_type
from data_ingestion.utils.types import SourceType
from extraction import pdf_extraction as extraction

_PROGRESS = Optional[Callable[[str, int, str], None]]


def run_upload_pipeline(
    file_path: Path,
    source_type: SourceType,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    """Full upload job by ``source_type``."""
    file_path = Path(file_path)

    if source_type == "pdf":
        pdf_path = prepare_pdf_source(file_path)
        pages_grouped, unit_context, outline_index = extraction.run_pdf_extraction(
            pdf_path,
            on_progress=on_progress,
        )
        result = extraction.run_post_extraction_validation(
            pages_grouped,
            unit_context,
            pdf_path=pdf_path,
            outline_index=outline_index,
            api_key=api_key,
            on_progress=on_progress,
        )
        return tag_tables_with_source_type(result, "pdf")

    if source_type in ("excel", "csv"):
        return run_spreadsheet_upload_pipeline(
            file_path,
            source_type,
            api_key=api_key,
            on_progress=on_progress,
        )

    raise ValueError(f"Unknown source_type: {source_type}")
