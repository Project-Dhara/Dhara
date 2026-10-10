"""
Excel / CSV upload path: data ingestion → ``PreValidationInput`` → validation.

PDF uploads still use the legacy branch in ``pipeline.run_upload_pipeline``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Literal, Optional

from data_ingestion import csv as ingest_csv
from data_ingestion import excel as ingest_excel
from data_ingestion.utils.enrich import tag_tables_with_source_type
from data_ingestion.utils.types import PreValidationInput
from extraction import pdf_extraction as extraction

SpreadsheetSourceType = Literal["excel", "csv"]
_PROGRESS = Optional[Callable[[str, int, str], None]]


def ingest_spreadsheet_path(path: Path, source_type: SpreadsheetSourceType) -> PreValidationInput:
    path = Path(path)
    if source_type == "excel":
        return ingest_excel.ingest_path(path)
    if source_type == "csv":
        return ingest_csv.ingest_path(path)
    raise ValueError(f"Expected excel or csv, got {source_type!r}")


def run_validation_from_pre_input(
    pre: PreValidationInput,
    source_type: SpreadsheetSourceType,
    *,
    api_key: Optional[str] = None,
    on_progress: _PROGRESS = None,
) -> Dict[int, Dict]:
    """Shared confidence + LLM step for spreadsheet ``PreValidationInput``."""
    pages_grouped = pre.get("pages_grouped") or {}
    unit_context = pre.get("unit_context") or {}

    if not pages_grouped:
        if on_progress:
            on_progress("done", 100, "No tables found after data ingestion")
        return {}

    result = extraction.run_post_extraction_validation(
        pages_grouped,
        unit_context,
        pdf_path=None,
        outline_index={},
        api_key=api_key,
        on_progress=on_progress,
    )
    return tag_tables_with_source_type(result, source_type)


def run_spreadsheet_upload_pipeline(
    file_path: Path,
    source_type: SpreadsheetSourceType,
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
