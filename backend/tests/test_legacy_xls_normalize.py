"""Tests for upload-time legacy .xls → Unicode .xlsx normalize."""
from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pytest

from app.services.ingestion.legacy_xls import LegacyXlsError, normalize_excel_upload

_LABOUR = Path(
    r"C:\Users\Sunny Rahul\Downloads\informationrequiredtransportlabourdeptt_\6.chap6c (labour).xls"
)
_TRANSPORT = Path(
    r"C:\Users\Sunny Rahul\Downloads\informationrequiredtransportlabourdeptt_\10.chap10(transport).xls"
)


def test_non_xls_passthrough():
    name, data = normalize_excel_upload("table.xlsx", b"not-really-xlsx")
    assert name == "table.xlsx"
    assert data == b"not-really-xlsx"


def test_reject_xlsx_renamed_as_xls():
    wb = openpyxl.Workbook()
    wb.active["A1"] = "hello"
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(LegacyXlsError, match="not a legacy BIFF"):
        normalize_excel_upload("renamed.xls", buf.getvalue())


def test_reject_empty_xls_name():
    with pytest.raises(LegacyXlsError, match="empty"):
        normalize_excel_upload("empty.xls", b"")


@pytest.mark.skipif(not _LABOUR.is_file(), reason="labour sample .xls not on disk")
def test_labour_xls_converts_unicode_and_merges():
    raw = _LABOUR.read_bytes()
    name, data = normalize_excel_upload(_LABOUR.name, raw)
    assert name == "6.chap6c (labour).xlsx"

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    assert wb.sheetnames[0] == "6.2"
    ws = wb["6.2"]
    assert "श्रम" in str(ws["A1"].value or "")
    assert "उद्योग" in str(ws["A2"].value or "")
    # Merges restored (top-left holds value; slaves blank in grid via merge)
    assert any(str(r).startswith("A1:") for r in ws.merged_cells.ranges)


@pytest.mark.skipif(not _TRANSPORT.is_file(), reason="transport sample .xls not on disk")
def test_transport_xls_chanakya_headers():
    name, data = normalize_excel_upload(_TRANSPORT.name, _TRANSPORT.read_bytes())
    assert name.endswith(".xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb[wb.sheetnames[0]]
    assert "परिवहन" in str(ws["A1"].value or "")
    assert "वाहन" in str(ws["B4"].value or "")
