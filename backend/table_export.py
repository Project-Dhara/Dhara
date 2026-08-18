"""Builds a clean single-sheet .xlsx from an extracted table's own columns
and rows -- preserving the extractor's already-parsed structure (resolved
merged headers, one row per record) so a downloaded dataset reflects what
was actually cataloged, rather than a re-flattened reconstruction.
"""

from io import BytesIO

import openpyxl


def table_to_excel_bytes(table: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (str(table.get("sheet") or "Table"))[:31] or "Table"

    columns = table.get("columns") or []
    rows = table.get("rows") or []

    ws.append(columns)
    for row in rows:
        ws.append([row.get(col) for col in columns])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
