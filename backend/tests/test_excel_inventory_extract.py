"""Regression: rectangular Excel inventories must keep all data rows."""
from __future__ import annotations

import io

import openpyxl

from extraction.extractor import TableExtractor


def _sandbox_bytes() -> bytes:
    """Minimal workbook mirroring 'Data Points - Sandbox.xlsx' failure mode."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data points"
    headers = [
        "Serial Number",
        "Table Name",
        "Variables (Summary)",
        "Unit of Observation",
        "Time Period",
        "Geography",
        "Source Document",
        "Department",
    ]
    ws.append(headers)
    rows = [
        [1, "Scheme Summary (Basic Statistics)", "Scheme name, beneficiaries, budget", "Scheme", "Up to Mar 2023", "State", "Write-up", "MSW"],
        [2, "KPI Monitoring Framework", "Applications, approvals", "District–Month", "Monthly", "District", "Write-up", "MSW"],
        [3, "Scheme Performance (Annual)", "Applications, beneficiaries", "Scheme-Year", "FY 2023–24", "State", "Write-up", "MSW"],
        [4, "Financial Statements", "Revenue, capital", "Scheme × Year", "FY 2023–24", "State", "Write-up", "MSW"],
        [5, "Physical Targets", "Beneficiaries", "Scheme-Year", "FY 2023–24", "State", "Write-up", "MSW"],
        [6, "Outcome Budget Master Table", "Indicators, baseline", "Scheme × Indicator", "2017–18", "State", "Outcome Budget", "MSW"],
        ["7A", "Pension Scheme Operations", "Aadhaar %, beneficiaries", "Scheme-Year", "2017–18", "State", "Outcome Budget", "MSW"],
        ["7B", "Infrastructure / Service Delivery", "Camps, centres", "Scheme-Year", "2017–18", "District/State", "Outcome Budget", "MSW"],
        ["7C", "Institutional Care (Homes)", "Capacity, residents", "Facility-Year", "2017–18", "Facility-level", "Outcome Budget", "MSW"],
        [8, "Monthly Expenditure Report", "Allocation, monthly spend", "Scheme-Month", "Monthly", "State", "Expenditure", "MSW"],
        [9, "Annual Plan Tables", "Outlay, targets", "Scheme-Year", "FY 2016–17", "State", "Annual Plan", "MSW"],
        [10, "Budget Line Items", "Demand no., scheme", "Scheme-Year", "FY 2024–25", "State", "Budget", "MSW"],
    ]
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _multi_table_sheet_bytes() -> bytes:
    """Two CRS-style tables on one sheet + a footnote mentioning TABLE D-18."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Combined Tables"
    ws.append([None] * 6)
    ws.append(["D-14"] * 6)
    ws.append(["INFANT DEATHS BY AGE (URBAN)"] * 6)
    ws.append(["SL. NO.", "AGE", "MALE", "FEMALE", "OTHER", "TOTAL"])
    ws.append([1, "< 7 DAYS", 10, 8, 0, 18])
    ws.append([2, "7-28 DAYS", 5, 4, 0, 9])
    ws.append([None, "ALL", None, None, None, None])
    ws.append([None] * 6)
    ws.append(["Notes"] + [None] * 5)
    ws.append(["Figures exclude cases pending verification."] + [None] * 5)
    ws.append([None] * 6)
    ws.append([None] * 6)
    ws.append(["D-18"] * 6)
    ws.append(["PREGNANCY RELATED DEATHS (URBAN)"] * 6)
    ws.append(["SL. NO.", "OCCUPATION", "<15", "15-19", "20-24", "25-29"])
    ws.append([1, "PROFESSIONAL", 0, 0, 2, 1])
    ws.append([2, "SERVICE WORKERS", 0, 1, 0, 0])
    ws.append([None] * 6)
    ws.append(
        ["TABLE D-18 repeated in a footnote; do not treat this as a third table."]
        + [None] * 5
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_table_name_header_is_not_a_table_marker():
    assert not TableExtractor._has_table_marker(
        ["Serial Number", "Table Name", "Variables (Summary)"]
    )
    assert TableExtractor._has_table_marker(["TABLE: D-12"] + [None] * 5)
    assert TableExtractor._has_table_marker(["TABLE B-6"])
    assert TableExtractor._has_table_marker(["D-14"] * 6)
    assert not TableExtractor._has_table_marker(
        ["TABLE D-18 repeated in a footnote; do not treat this as a third table."]
    )
    assert not TableExtractor._has_table_marker(
        ["6", "Outcome Budget Master Table", "Indicators, baseline"]
    )


def test_data_points_inventory_keeps_all_rows():
    tables = TableExtractor(skip_llm=True).extract_from_file(
        _sandbox_bytes(), "Data Points - Sandbox.xlsx"
    )
    assert len(tables) == 1
    t = tables[0]
    assert t["columns"][:3] == ["Serial Number", "Table Name", "Variables (Summary)"]
    assert t["row_count"] == 12
    first = t["rows"][0]
    assert first["Serial Number"] in (1, 1.0)
    assert first["Table Name"] == "Scheme Summary (Basic Statistics)"
    serials = [
        str(r["Serial Number"]).rstrip("0").rstrip(".")
        if isinstance(r["Serial Number"], float)
        else str(r["Serial Number"])
        for r in t["rows"]
    ]
    assert "1" in serials
    assert "7A" in serials
    assert "7C" in serials
    assert "10" in serials


def test_multiple_tables_one_sheet_extracts_both():
    tables = TableExtractor(skip_llm=True).extract_from_file(
        _multi_table_sheet_bytes(), "04_multiple_tables_one_sheet.xlsx"
    )
    assert len(tables) == 2
    assert tables[0]["table_id"] == "D-14"
    assert tables[1]["table_id"] == "D-18"
    assert tables[0]["row_count"] >= 2
    assert tables[1]["row_count"] >= 2
    assert all("footnote" not in str(t.get("title") or "").lower() for t in tables)
