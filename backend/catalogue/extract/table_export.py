"""Builds a clean single-sheet .xlsx from an extracted table's own columns
and rows -- preserving the extractor's already-parsed structure (resolved
merged headers, one row per record) so a downloaded dataset reflects what
was actually cataloged, rather than a re-flattened reconstruction.

Supports both Excel-pipeline tables (columns: list[str], rows: list[dict])
and PDF-pipeline tables (columns: list[{name, …}], rows: list[list]).
"""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import openpyxl


def _column_names(table: dict) -> list[str]:
    columns = table.get("columns") or []
    names: list[str] = []
    for i, col in enumerate(columns):
        if isinstance(col, str):
            names.append(col or f"Col_{i + 1}")
        elif isinstance(col, dict):
            names.append(str(col.get("name") or f"Col_{i + 1}"))
        else:
            names.append(f"Col_{i + 1}")
    return names


def _iter_row_values(row: Any, col_names: list[str]) -> list[Any]:
    if isinstance(row, dict):
        return [row.get(c) for c in col_names]
    if isinstance(row, (list, tuple)):
        vals = list(row[: len(col_names)])
        while len(vals) < len(col_names):
            vals.append(None)
        return vals
    return [None] * len(col_names)


def _safe_sheet_title(name: Any) -> str:
    """Excel forbids \\ / ? * [ ] : in worksheet titles (max 31 chars)."""
    cleaned = re.sub(r'[:\\/?*\[\]]+', ' ', str(name or 'Table'))
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(" '") or 'Table'
    return cleaned[:31] or 'Table'


def table_to_excel_bytes(table: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    sheet_name = table.get("sheet") or table.get("title") or table.get("table_id") or "Table"
    ws.title = _safe_sheet_title(sheet_name)

    col_names = _column_names(table)
    rows = table.get("rows") or []

    if col_names:
        ws.append(col_names)
    for row in rows:
        ws.append(_iter_row_values(row, col_names))

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def safe_download_stem(table: dict, fallback: str = "table") -> str:
    """Filesystem-safe basename (no extension) for a table download."""
    raw = (
        table.get("title")
        or table.get("table_id")
        or table.get("id")
        or fallback
    )
    stem = re.sub(r"[^\w.\-]+", "_", str(raw), flags=re.UNICODE).strip("._")
    return (stem or fallback)[:80]
