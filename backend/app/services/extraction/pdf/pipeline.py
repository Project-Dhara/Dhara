"""
PDF upload step 1 entry (before grouping): extract → PreValidationInput → validate.

Call ``run_pdf_upload_pipeline`` from the upload job worker. Grouping / catalogue
steps run later via ``persist-approved`` (not this module).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from app.services.extraction.pdf.confidence_validation import run_post_extraction_validation
from app.services.extraction.pdf.extract import extract_pdf_to_pre_input
from app.services.ingestion.utils.enrich import tag_tables_with_source_type
from app.services.ingestion.contracts import PreValidationInput

_PROGRESS = Optional[Callable[[str, int, str], None]]


def validate_pre_input(
    pre: PreValidationInput,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    """Confidence split + LLM / heuristic validation for PDF ``PreValidationInput``."""
    pdf_path = Path(pre["source_path"]) if pre.get("source_path") else None
    outline_index = pre.get("outline_index") or {}
    result = run_post_extraction_validation(
        pre["pages_grouped"],
        pre["unit_context"],
        pdf_path=pdf_path,
        outline_index=outline_index,
        api_key=api_key,
        on_progress=on_progress,
    )
    return tag_tables_with_source_type(result, "pdf")


def run_pdf_upload_pipeline(
    file_path: Path,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    """End-to-end PDF step 1 for upload jobs."""
    pre = extract_pdf_to_pre_input(file_path, on_progress=on_progress)
    return validate_pre_input(pre, api_key=api_key, on_progress=on_progress)
