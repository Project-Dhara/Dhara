"""
Excel / CSV upload path: data ingestion → ``PreValidationInput`` → validation.

Spreadsheet and PDF step-1 validation share
``app.services.extraction.pdf.confidence_validation``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Optional

from app.services.ingestion import csv as ingest_csv
from app.services.ingestion import excel as ingest_excel
from app.services.extraction.pdf.confidence_validation import run_post_extraction_validation
from app.services.ingestion.utils.enrich import tag_tables_with_source_type
from app.services.ingestion.contracts import PreValidationInput, SourceType

_PROGRESS = Optional[Callable[[str, int, str], None]]


def ingest_spreadsheet_path(path: Path, source_type: SourceType) -> PreValidationInput:
    path = Path(path)
    if source_type == "excel":
        return ingest_excel.ingest_path(path)
    if source_type == "csv":
        return ingest_csv.ingest_path(path)
    raise ValueError(f"Expected excel or csv, got {source_type!r}")


def run_validation_from_pre_input(
    pre: PreValidationInput,
    source_type: SourceType,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    """Confidence + LLM validation for any ``PreValidationInput`` (PDF, Excel, CSV)."""
    pages_grouped = pre.get("pages_grouped") or {}
    unit_context = pre.get("unit_context") or {}

    if not pages_grouped:
        if on_progress:
            on_progress("done", 100, "No tables found after data ingestion")
        return {}

    pdf_path = Path(pre["source_path"]) if pre.get("source_path") else None
    outline_index = pre.get("outline_index") or {}

    result = run_post_extraction_validation(
        pages_grouped,
        unit_context,
        pdf_path=pdf_path,
        outline_index=outline_index,
        api_key=api_key,
        on_progress=on_progress,
    )
    return tag_tables_with_source_type(result, source_type)


def run_spreadsheet_upload_pipeline(
    file_path: Path,
    source_type: SourceType,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    """End-to-end job for .xlsx or .csv uploads."""

    def progress(stage: str, percent: int, message: str) -> None:
        if on_progress:
            on_progress(stage, percent, message)

    file_path = Path(file_path)
    progress("ingest", 10, f"Data ingestion ({source_type}): {file_path.name}")
    pre = ingest_spreadsheet_path(file_path, source_type)

    n_units = len(pre.get("pages_grouped") or {})
    n_cands = sum(len(v) for v in (pre.get("pages_grouped") or {}).values())
    progress("ingest", 45, f"{n_cands} grid candidate(s) in {n_units} unit(s)")

    return run_validation_from_pre_input(
        pre,
        source_type,
        api_key=api_key,
        on_progress=on_progress,
    )
