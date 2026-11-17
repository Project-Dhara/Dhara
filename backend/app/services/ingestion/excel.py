"""Excel data ingestion: workbook → table grid candidates (no PyMuPDF, no LLM).

Primary path: layout-driven extractor (``layout_table_extractor``).
Legacy ``TableExtractor`` grid/blocks path is retained as a fallback so a
failure in the new engine does not break upload → validation → Preview.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import openpyxl

from app.services.ingestion.utils.dataframe_build import dataframe_from_spreadsheet_rows
from app.services.ingestion.utils.grid import (
    block_to_rows,
    context_text_from_grid,
    strip_uniform_banner_rows,
)
from app.services.ingestion.contracts import PagesGrouped, PreValidationInput, UnitContextText
from app.services.ingestion.wizard.extractor import TableExtractor
from app.services.extraction.pdf.utils.header_utils import extract_in_grid_caption

logger = logging.getLogger(__name__)

INGEST_METHOD = "excel_grid"


def _attach_in_grid_caption(df, caption: dict) -> None:
    """Restore title/id banners stripped before DataFrame build.

    Merged Excel title rows are fill-expanded across columns, then removed by
    ``strip_uniform_banner_rows`` so they do not become fake header levels.
    Capture the caption first and re-attach it here; otherwise title inference
    falls back to unit-context lines like ``Sheet: <sheet name>``.
    """
    if df is None:
        return
    attrs = getattr(df, "attrs", None)
    if attrs is None:
        return
    title = (caption.get("title") or "").strip()
    banner_id = (caption.get("table_id_label") or "").strip()
    if title and not (attrs.get("dhara_table_caption") or "").strip():
        attrs["dhara_table_caption"] = title
    if banner_id and not (attrs.get("dhara_banner_table_id") or "").strip():
        attrs["dhara_banner_table_id"] = banner_id


def _legacy_ingest_bytes(content: bytes, filename: str = "") -> PreValidationInput:
    """Previous grid/block ingest (TableExtractor._find_blocks)."""
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
            # Caption before strip — merge-filled banners are removed next.
            caption = extract_in_grid_caption(rows)
            grid_rows = strip_uniform_banner_rows(rows)
            # Spreadsheet header detect — not PDF dataframe_from_extracted_rows.
            df = dataframe_from_spreadsheet_rows(grid_rows)
            if df is None or getattr(df, "empty", True):
                continue
            _attach_in_grid_caption(df, caption)
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


def ingest_bytes(content: bytes, filename: str = "") -> PreValidationInput:
    from app.services.ingestion.layout_ingest import ingest_with_layout_extractor

    try:
        pre = ingest_with_layout_extractor(
            source_type="excel",
            filename=filename or "upload.xlsx",
            content=content,
        )
        if pre.get("pages_grouped"):
            return pre
        logger.info(
            "layout extractor found no Excel tables for %s; trying legacy ingest",
            filename or "upload.xlsx",
        )
    except Exception:
        logger.exception(
            "layout Excel ingest failed for %s; falling back to legacy",
            filename or "upload.xlsx",
        )
    return _legacy_ingest_bytes(content, filename)


def ingest_path(path: Path) -> PreValidationInput:
    from app.services.ingestion.layout_ingest import ingest_with_layout_extractor

    path = Path(path)
    try:
        pre = ingest_with_layout_extractor(
            source_type="excel",
            filename=path.name,
            path=path,
        )
        if pre.get("pages_grouped"):
            return pre
        logger.info(
            "layout extractor found no Excel tables for %s; trying legacy ingest",
            path.name,
        )
    except Exception:
        logger.exception(
            "layout Excel ingest failed for %s; falling back to legacy",
            path.name,
        )
    return _legacy_ingest_bytes(path.read_bytes(), path.name)
