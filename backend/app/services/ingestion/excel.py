"""Excel data ingestion: workbook → table grid candidates (no PyMuPDF, no LLM)."""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl

from app.services.ingestion.utils.grid import (
    block_to_rows,
    context_text_from_grid,
    strip_uniform_banner_rows,
)
from app.services.ingestion.contracts import PagesGrouped, PreValidationInput, UnitContextText
from app.services.ingestion.wizard.extractor import TableExtractor
from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows

INGEST_METHOD = "excel_grid"


def ingest_bytes(content: bytes, filename: str = "") -> PreValidationInput:
    extractor = TableExtractor(skip_llm=True)
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    pages_grouped: PagesGrouped = {}
    unit_context: UnitContextText = {}
    unit = 0

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        grid = extractor._filled_grid(ws)
        if not grid:
            continue
        blocks = extractor._find_blocks(grid)
        if not blocks:
            blocks = [(0, len(grid) - 1)]

        for start, end in blocks:
            block = grid[start : end + 1]
            rows = block_to_rows(block)
            grid_rows = strip_uniform_banner_rows(rows)
            df = dataframe_from_extracted_rows(grid_rows)
            if df is None or getattr(df, "empty", True):
                continue
            unit += 1
            pages_grouped[unit] = [
                {
                    "page": unit,
                    "method": INGEST_METHOD,
                    "df": df,
                    "bbox": None,
                    "sheet": sheet_name,
                    "source_file": filename,
                }
            ]
            unit_context[unit] = context_text_from_grid(
                rows, sheet_name=sheet_name, filename=filename
            )

    return PreValidationInput(
        pages_grouped=pages_grouped,
        unit_context=unit_context,
        source_type="excel",
        source_file=filename,
    )


def ingest_path(path: Path) -> PreValidationInput:
    return ingest_bytes(path.read_bytes(), path.name)
