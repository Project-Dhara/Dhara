"""Blank-stub percentage rows (empty Year + parenthetical shares) must be kept."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.stamp import _restore_missing_data_rows_from_candidate
from app.services.extraction.pdf.utils.header_utils import (
    _is_measurement_number,
    _is_numeric_cell,
    dataframe_from_extracted_rows,
    detect_header_rows,
)


HEADERS = [
    "Year",
    "Graduate And above",
    "Matriculates Hr.Sec. or Equivalent exam",
    "Below Matric and other Literate",
    "Illiterate and Not Stated",
]

RAW_GRID = [
    HEADERS,
    ["1991", "28815", "37043", "41435", "164727"],
    ["", "(10.6)", "(13.6)", "(15.2)", "(60.6)"],
    ["2000", "57542", "52426", "82579", "124829"],
    ["", "(18.1)", "(16.6)", "(26.0)", "(39.3)"],
    ["2001", "39602", "59941", "62868", "133876"],
    ["", "(13.37)", "(20.23)", "(21.22)", "*(45.18)"],
]


def test_parenthetical_shares_are_numeric_measurements():
    assert _is_numeric_cell("(10.6)")
    assert _is_numeric_cell("*(45.18)")
    assert _is_measurement_number("(10.6)")
    assert _is_measurement_number("*(45.18)")


def test_detect_header_does_not_skip_blank_stub_percent_rows():
    header_count, skip = detect_header_rows(RAW_GRID, 5)
    assert header_count == 1
    assert skip == []
    # Percentage rows must remain in the body (indices 2, 4, 6).
    assert 2 not in skip and 4 not in skip and 6 not in skip


def test_dataframe_keeps_blank_stub_percent_rows():
    df = dataframe_from_extracted_rows(RAW_GRID)
    assert df.shape[0] == 6
    assert df.shape[1] == 5

    def _cell(v):
        if v is None:
            return ""
        s = str(v).strip()
        return "" if s.lower() in {"", "none", "nan"} else s

    years = [_cell(v) for v in df.iloc[:, 0].tolist()]
    assert years == ["1991", "", "2000", "", "2001", ""]
    assert _cell(df.iloc[1, 1]) == "(10.6)"
    assert _cell(df.iloc[5, 4]) == "*(45.18)"


def test_restore_inserts_blank_stub_rows_llm_dropped():
    cand = dataframe_from_extracted_rows(RAW_GRID)
    # LLM kept only the three year rows (common failure mode).
    table = {
        "columns": [{"name": n} for n in list(cand.columns)],
        "rows": [
            ["1991", "28815", "37043", "41435", "164727"],
            ["2000", "57542", "52426", "82579", "124829"],
            ["2001", "39602", "59941", "62868", "133876"],
        ],
        "notes": [],
    }
    _restore_missing_data_rows_from_candidate(table, cand)
    assert len(table["rows"]) == 6
    assert table["rows"][1][0] in (None, "")
    assert table["rows"][1][1] == "(10.6)"
    assert table["rows"][5][4] == "*(45.18)"
    assert any("blank-stub" in n for n in table["notes"])


def test_restore_does_not_reinsert_column_index_strip():
    cand = pd.DataFrame(
        [
            ["1991", "10", "20", "30"],
            ["(1)", "(2)", "(3)", "(4)"],  # index strip — must stay dropped
            ["2000", "11", "21", "31"],
        ],
        columns=["Year", "A", "B", "C"],
    )
    table = {
        "columns": [{"name": n} for n in list(cand.columns)],
        "rows": [
            ["1991", "10", "20", "30"],
            ["2000", "11", "21", "31"],
        ],
        "notes": [],
    }
    _restore_missing_data_rows_from_candidate(table, cand)
    assert len(table["rows"]) == 2
