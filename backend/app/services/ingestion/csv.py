"""CSV data ingestion: file → table grid candidates (no PyMuPDF, no LLM).

Primary path: layout-driven extractor (``layout_table_extractor``).
Legacy single-table CSV reader is retained as a fallback.
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from app.services.ingestion.utils.dataframe_build import dataframe_from_spreadsheet_rows
from app.services.ingestion.utils.grid import cell_str, context_text_from_grid
from app.services.ingestion.contracts import PagesGrouped, PreValidationInput, UnitContextText

logger = logging.getLogger(__name__)

INGEST_METHOD = "csv_grid"


def _legacy_ingest_bytes(content: bytes, filename: str = "") -> PreValidationInput:
    text = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Could not decode CSV (expected utf-8 or latin-1)")

    reader = csv.reader(io.StringIO(text))
    rows = [list(r) for r in reader if any(cell_str(c) for c in r)]
    pages_grouped: PagesGrouped = {}
    unit_context: UnitContextText = {}
    if not rows:
        return PreValidationInput(
            pages_grouped=pages_grouped,
            unit_context=unit_context,
            source_type="csv",
            source_file=filename,
        )

    # Spreadsheet header detect — not PDF dataframe_from_extracted_rows.
    df = dataframe_from_spreadsheet_rows(rows)
    if df is None or getattr(df, "empty", True):
        return PreValidationInput(
            pages_grouped=pages_grouped,
            unit_context=unit_context,
            source_type="csv",
            source_file=filename,
        )

    unit = 1
    pages_grouped[unit] = [
        {
            "page": unit,
            "method": INGEST_METHOD,
            "df": df,
            "bbox": None,
            "sheet": Path(filename).stem or "csv",
            "source_file": filename,
        }
    ]
    unit_context[unit] = context_text_from_grid(rows, sheet_name="csv", filename=filename)
    return PreValidationInput(
        pages_grouped=pages_grouped,
        unit_context=unit_context,
        source_type="csv",
        source_file=filename,
    )


def ingest_bytes(content: bytes, filename: str = "") -> PreValidationInput:
    from app.services.ingestion.layout_ingest import ingest_with_layout_extractor

    try:
        pre = ingest_with_layout_extractor(
            source_type="csv",
            filename=filename or "upload.csv",
            content=content,
        )
        if pre.get("pages_grouped"):
            return pre
        logger.info(
            "layout extractor found no CSV tables for %s; trying legacy ingest",
            filename or "upload.csv",
        )
    except Exception:
        logger.exception(
            "layout CSV ingest failed for %s; falling back to legacy",
            filename or "upload.csv",
        )
    return _legacy_ingest_bytes(content, filename)


def ingest_path(path: Path) -> PreValidationInput:
    from app.services.ingestion.layout_ingest import ingest_with_layout_extractor

    path = Path(path)
    try:
        pre = ingest_with_layout_extractor(
            source_type="csv",
            filename=path.name,
            path=path,
        )
        if pre.get("pages_grouped"):
            return pre
        logger.info(
            "layout extractor found no CSV tables for %s; trying legacy ingest",
            path.name,
        )
    except Exception:
        logger.exception(
            "layout CSV ingest failed for %s; falling back to legacy",
            path.name,
        )
    return _legacy_ingest_bytes(path.read_bytes(), path.name)
