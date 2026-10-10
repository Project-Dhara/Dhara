"""Extracts a single sheet from a source workbook into its own standalone
.xlsx file, preserving the original formatting (cell styles, merged
ranges, column widths, row heights) -- unlike table_export.py, which
writes a clean re-flattened version from the extractor's parsed columns.

This exists because a dataset's "download" should give back the actual
government table as published, not a reformatted reconstruction.
"""

import copy
from io import BytesIO

import openpyxl


def extract_sheet_with_formatting(wb, sheet_name: str) -> bytes:
    source_ws = wb[sheet_name]

    new_wb = openpyxl.Workbook()
    new_ws = new_wb.active
    new_ws.title = str(sheet_name)[:31] or "Sheet1"

    for row in source_ws.iter_rows():
        for cell in row:
            new_cell = new_ws.cell(row=cell.row, column=cell.column, value=cell.value)
            if cell.has_style:
                new_cell.font = copy.copy(cell.font)
                new_cell.border = copy.copy(cell.border)
                new_cell.fill = copy.copy(cell.fill)
                new_cell.number_format = cell.number_format
                new_cell.protection = copy.copy(cell.protection)
                new_cell.alignment = copy.copy(cell.alignment)

    for merged_range in source_ws.merged_cells.ranges:
        new_ws.merge_cells(str(merged_range))

    for col_letter, dim in source_ws.column_dimensions.items():
        if dim.width:
            new_ws.column_dimensions[col_letter].width = dim.width

    for row_idx, dim in source_ws.row_dimensions.items():
        if dim.height:
            new_ws.row_dimensions[row_idx].height = dim.height

    buf = BytesIO()
    new_wb.save(buf)
    return buf.getvalue()


def extract_sheet_with_formatting_from_bytes(file_bytes: bytes, sheet_name: str) -> bytes:
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    return extract_sheet_with_formatting(wb, sheet_name)
