"""Index-strip body rows and name+number phantom columns."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from app.services.extraction.pdf.utils.dataframe_build import dataframe_from_extracted_rows
from app.services.extraction.pdf.utils.grid_repair import (
    collapse_index_leaf_phantom_columns,
    _coalesce_split_cell_values,
)


def test_coalesce_decimal_split_fragments():
    assert _coalesce_split_cell_values("30708.2", "5") == "30708.25"
    assert _coalesce_split_cell_values("2230.", "8") == "2230.8"


def test_collapse_index_leaf_phantoms():
    df = pd.DataFrame(
        [
            ["Kollam", None, "30708.2", "5", "2230.8", None],
            ["Idukki", None, "16987.1", "7", "0", None],
        ],
        columns=["District", "2", "Land put to non agricultural use", "5", "Cultivable waste", "9"],
    )
    df.attrs["dhara_column_meta"] = [
        {"name": "District", "header_path": ["District"]},
        {"name": "2", "header_path": ["District", "2"]},
        {"name": "Land put to non agricultural use", "header_path": ["Land put to non agricultural use"]},
        {"name": "5", "header_path": ["Land put to non agricultural use", "5"]},
        {"name": "Cultivable waste", "header_path": ["Cultivable waste"]},
        {"name": "9", "header_path": ["Cultivable waste", "9"]},
    ]
    out = collapse_index_leaf_phantom_columns(df)
    assert list(out.columns) == [
        "District",
        "Land put to non agricultural use",
        "Cultivable waste",
    ]
    assert out.iloc[0, 1] == "30708.25"


def test_dataframe_drops_leading_index_strip():
    rows = [
        ["Sl. No.", "District", "Forest", "Cultivable waste"],
        ["1", "2", "3", "4"],
        ["1", "Kollam", "81438", "2230.8"],
        ["2", "Idukki", "198413", "0"],
    ]
    df = dataframe_from_extracted_rows(rows)
    assert list(df.iloc[0]) == ["1", "Kollam", "81438", "2230.8"]
    assert df.shape[0] == 2
