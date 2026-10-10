"""Excel multi-row / merged column headings must stay multi-level."""
from __future__ import annotations

from app.services.metadata.metadata_llm import _detect_header_rows, _flatten_headers, _heuristic_structure
from app.services.ingestion.wizard.extractor import TableExtractor


def test_detect_keeps_merged_group_and_leaf_header_rows():
    # Merge-filled grid: URBAN spans Male|Female, RURAL spans Male|Female.
    body = [
        ["State", "URBAN", "URBAN", "RURAL", "RURAL"],
        ["State", "Male", "Female", "Male", "Female"],
        ["01", 10, 20, 30, 40],
        ["02", 11, 21, 31, 41],
    ]
    n_cols = 5
    header_rows, skip = _detect_header_rows(body, n_cols)
    assert skip == []
    assert header_rows == 2


def test_flatten_joins_group_and_leaf():
    matrix = [
        ["State", "URBAN", "URBAN", "RURAL", "RURAL"],
        ["State", "Male", "Female", "Male", "Female"],
    ]
    cols = _flatten_headers(matrix, 5)
    assert cols[0] == "State"
    assert cols[1] == "URBAN / Male"
    assert cols[2] == "URBAN / Female"
    assert cols[3] == "RURAL / Male"
    assert cols[4] == "RURAL / Female"


def test_heuristic_structure_preserves_two_header_rows():
    body = [
        ["State", "URBAN", "URBAN", "RURAL", "RURAL"],
        ["State", "Male", "Female", "Male", "Female"],
        ["01", 10, 20, 30, 40],
    ]
    structure = _heuristic_structure(body, 5)
    assert structure["header_rows"] == 2
    assert structure["columns"][1] == "URBAN / Male"


def test_inventory_sheet_still_single_header_row():
    body = [
        ["Scheme name", "Beneficiaries", "Budget", "Year"],
        ["S1", 100, 2000, 2020],
        ["S2", 110, 2100, 2021],
    ]
    header_rows, _ = _detect_header_rows(body, 4)
    assert header_rows == 1


def test_extract_table_keeps_raw_header_rows():
    # Simulate merge-filled sheet body after title strip.
    grid = [
        ["Live births by area"] + [None] * 4,
        ["State", "URBAN", "URBAN", "RURAL", "RURAL"],
        ["State", "Male", "Female", "Male", "Female"],
        ["01", 10, 20, 30, 40],
        ["02", 11, 21, 31, 41],
    ]
    ext = TableExtractor(skip_llm=True)
    table = ext._extract_table(grid, 0, len(grid) - 1, "Sheet1", "demo.xlsx", 0)
    assert table is not None
    assert len(table["raw_header_rows"]) == 2
    assert table["raw_header_rows"][0][1] == "URBAN"
    assert table["raw_header_rows"][1][1] == "Male"
    assert "URBAN" in table["columns"][1] and "Male" in table["columns"][1]
