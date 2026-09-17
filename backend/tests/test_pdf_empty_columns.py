"""Regression: empty named measure columns must stay empty and keep their headers."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf.pdf_header_utils import repair_glued_numeric_cells
from pdf.pdf_table_confidence import (
    clean_dataframe_light,
    classify_page,
    profile_table,
    table_dict_from_df,
)


def test_repair_glued_prefers_trailing_empties():
    rows = [
        ["a", "Food", "100", "", "", "", "118.4 120 121.6 115.3", None, None, None],
    ]
    out = repair_glued_numeric_cells(rows)
    assert out[0][6:10] == ["118.4", "120", "121.6", "115.3"]
    assert out[0][3] in ("", None)
    assert out[0][4] in ("", None)
    assert out[0][5] in ("", None)


def test_repair_glued_uses_preceding_empties_when_needed():
    # Four values packed into the last column; earlier slots empty.
    rows = [["x", "", "", "", "10 20 30 40"]]
    out = repair_glued_numeric_cells(rows)
    assert out[0] == ["x", "10", "20", "30", "40"]


def test_repair_glued_right_aligns_into_combined_window():
    # Four values glued mid-row: not enough trailing or leading alone, but enough combined.
    # Right-align into the empty window so an earlier unused period stays blank.
    rows = [["id", "", "", "1 2 3 4", "", "", "tail"]]
    out = repair_glued_numeric_cells(rows)
    assert out[0] == ["id", "", "1", "2", "3", "4", "tail"]


def test_clean_keeps_named_empty_columns_and_meta():
    df = pd.DataFrame(
        [
            ["1", "Food", "100", None, None, "118.4", "120"],
            ["a", "Cereals", "13", None, None, "120.3", "121"],
        ],
        columns=["Group", "Sub-Group", "Weight", "Jan", "Feb", "Sep", "Oct"],
    )
    df.attrs["dhara_column_meta"] = [
        {"name": n, "header_group": None, "header_path": [n]}
        for n in df.columns
    ]
    cleaned = clean_dataframe_light(df)
    assert list(cleaned.columns) == ["Group", "Sub-Group", "Weight", "Jan", "Feb", "Sep", "Oct"]
    assert cleaned["Jan"].isna().all()
    assert cleaned["Feb"].isna().all()
    meta = cleaned.attrs["dhara_column_meta"]
    assert [m["name"] for m in meta] == list(cleaned.columns)


def test_clean_still_drops_placeholder_empty_columns():
    df = pd.DataFrame(
        [["a", "1"], ["b", "2"]],
        columns=["Name", "Col_2"],
    )
    df["Col_3"] = None
    cleaned = clean_dataframe_light(df)
    assert list(cleaned.columns) == ["Name", "Col_2"]


def test_table_dict_does_not_relabel_after_empty_months():
    df = pd.DataFrame(
        [
            ["1", "Food", "100", None, None, None, None, "118.4", "120", "121.6", "115.3"],
        ],
        columns=["Group", "Sub-Group", "Weight", "Jan", "Feb", "Mar", "Apr", "Sep", "Oct", "Nov", "Dec"],
    )
    df.attrs["dhara_column_meta"] = [
        {"name": n, "header_group": None, "header_path": [n]} for n in df.columns
    ]
    table = table_dict_from_df(df, page_num=1, method="pymupdf_lines")
    names = [c["name"] for c in table["columns"]]
    assert names == list(df.columns)
    row = table["rows"][0]
    assert row[3:7] == [None, None, None, None]
    assert row[7:11] == ["118.4", "120", "121.6", "115.3"]


def test_profile_ignores_all_null_columns_for_fill_rate():
    df = pd.DataFrame(
        {
            "A": ["x", "y"],
            "Jan": [None, None],
            "Sep": ["1", "2"],
        }
    )
    info = profile_table(df)
    # Without ignoring Jan, ratio would be 4/6; with ignore, 4/4.
    assert info["nonempty_ratio"] == 1.0
    assert info["n_cols"] == 3


def test_classify_page_stays_high_with_empty_named_months():
    df = pd.DataFrame(
        [
            ["1", "Food", "100", None, None, "118.4", "120", "121.6", "115.3"],
            ["a", "Cereals", "13.4", None, None, "120.3", "121", "118.4", "117.1"],
            ["b", "Pulses", "6.9", None, None, "89", "92.1", "91.9", "91.4"],
        ],
        columns=["Group", "Sub-Group", "Weight", "Jan", "Feb", "Sep", "Oct", "Nov", "Dec"],
    )
    candidates = [{"method": "pymupdf_lines", "df": df, "bbox": [0, 0, 100, 100]}]
    bucket, reason, info = classify_page(candidates)
    assert bucket == "high", (bucket, reason, info)


if __name__ == "__main__":
    test_repair_glued_prefers_trailing_empties()
    test_repair_glued_uses_preceding_empties_when_needed()
    test_repair_glued_right_aligns_into_combined_window()
    test_clean_keeps_named_empty_columns_and_meta()
    test_clean_still_drops_placeholder_empty_columns()
    test_table_dict_does_not_relabel_after_empty_months()
    test_profile_ignores_all_null_columns_for_fill_rate()
    test_classify_page_stays_high_with_empty_named_months()
    print("ok")
