"""Excel/CSV DataFrame build must not use PDF header absorption on body rows."""
from __future__ import annotations

import io

import openpyxl

from app.services.ingestion import csv as ingest_csv
from app.services.ingestion import excel as ingest_excel
from app.services.ingestion.utils.dataframe_build import dataframe_from_spreadsheet_rows
from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows


def test_text_heavy_body_rows_kept_as_data():
    rows = [
        ["Name", "Type", "Status", "Region"],
        ["North Zone Office", "Primary", "Active", "North"],
        ["South Zone Office", "Secondary", "Pending", "South"],
        ["East Zone Office", "Primary", "Active", "East"],
    ]
    df = dataframe_from_spreadsheet_rows(rows)
    assert len(df) == 3
    assert list(df.columns) == ["Name", "Type", "Status", "Region"]
    assert list(df.iloc[0]) == ["North Zone Office", "Primary", "Active", "North"]


def test_short_code_body_rows_not_swallowed_as_headers():
    rows = [
        ["District", "Code", "Category"],
        ["NZ", "A1", "Admin"],
        ["SZ", "B2", "Admin"],
        ["EZ", "C3", "Ops"],
    ]
    df = dataframe_from_spreadsheet_rows(rows)
    assert len(df) == 3
    assert df.iloc[0, 0] == "NZ"
    assert df.iloc[2, 0] == "EZ"


def test_merge_filled_multilevel_headers_preserved():
    rows = [
        ["State", "URBAN", "URBAN", "RURAL", "RURAL"],
        ["State", "Male", "Female", "Male", "Female"],
        ["01", 10, 20, 30, 40],
        ["02", 11, 21, 31, 41],
    ]
    df = dataframe_from_spreadsheet_rows(rows)
    assert len(df) == 2
    meta = df.attrs.get("dhara_column_meta") or []
    paths = [tuple(m.get("header_path") or []) for m in meta]
    assert paths[0] == ("State",)
    assert paths[1] == ("URBAN", "Male")
    assert paths[2] == ("URBAN", "Female")
    assert paths[3] == ("RURAL", "Male")
    assert paths[4] == ("RURAL", "Female")


def test_spreadsheet_keeps_rows_pdf_flattener_can_mis_label():
    """Regression: catalogue-style prose inventory must keep all body rows."""
    rows = [
        ["Table Name", "Variables (Summary)", "Unit", "Remarks"],
        [
            "Scheme Summary Basic Statistics",
            "Scheme name, beneficiaries, budget allocated",
            "Scheme",
            "Annual rollup for districts",
        ],
        [
            "KPI Monitoring Dashboard Metrics",
            "Applications, approvals, pending backlog counts",
            "District",
            "Monthly operational snapshot",
        ],
        [
            "Beneficiary Coverage Report Detail",
            "Households covered, villages reached, outliers",
            "Block",
            "Quarterly field verification",
        ],
    ]
    ss = dataframe_from_spreadsheet_rows(rows)
    assert len(ss) == 3
    # First body cell stays in the body, not promoted into the column name.
    assert "Scheme Summary" in str(ss.iloc[0, 0])


def test_csv_ingest_keeps_leading_body_rows():
    raw = (
        "Name,Type,Status,Region\n"
        "North Zone Office,Primary,Active,North\n"
        "South Zone Office,Secondary,Pending,South\n"
        "East Zone Office,Primary,Active,East\n"
    ).encode("utf-8")
    pre = ingest_csv.ingest_bytes(raw, "zones.csv")
    df = pre["pages_grouped"][1][0]["df"]
    assert len(df) == 3
    assert df.iloc[0, 0] == "North Zone Office"


def test_excel_ingest_keeps_leading_body_rows():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Zones"
    ws.append(["Name", "Type", "Status", "Region"])
    ws.append(["North Zone Office", "Primary", "Active", "North"])
    ws.append(["South Zone Office", "Secondary", "Pending", "South"])
    buf = io.BytesIO()
    wb.save(buf)
    pre = ingest_excel.ingest_bytes(buf.getvalue(), "zones.xlsx")
    df = pre["pages_grouped"][1][0]["df"]
    assert len(df) == 2
    assert df.iloc[0, 0] == "North Zone Office"


def test_pdf_builder_untouched_for_same_grid():
    """PDF path still uses dataframe_from_extracted_rows (smoke import/call)."""
    rows = [
        ["Scheme name", "Beneficiaries", "Budget", "Year"],
        ["S1", 100, 2000, 2020],
    ]
    pdf_df = dataframe_from_extracted_rows(rows)
    assert len(pdf_df) == 1
    assert list(pdf_df.columns)[0] == "Scheme name"
