"""CSV data ingestion: file → table grid candidates (no PyMuPDF, no LLM)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from app.services.ingestion.utils.grid import cell_str, context_text_from_grid
from app.services.ingestion.contracts import PagesGrouped, PreValidationInput, UnitContextText
from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows

INGEST_METHOD = "csv_grid"


def ingest_bytes(content: bytes, filename: str = "") -> PreValidationInput:
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

    df = dataframe_from_extracted_rows(rows)
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


def ingest_path(path: Path) -> PreValidationInput:
    return ingest_bytes(path.read_bytes(), path.name)
