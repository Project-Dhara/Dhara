"""Explicit empty header cells (``''``) must not inherit neighbour labels."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_detect import (
    _fill_header_matrix,
    resolve_column_headers,
)
from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows


def test_fill_matrix_keeps_explicit_blank_between_particulars_and_years():
    """``''`` stays blank; ``None`` still receives year colspan fill."""
    header = [
        ["Particulars", "", "2018", None, "2019", None],
        [None, "", "Trivandrum", "Kerala", "Trivandrum", "Kerala"],
    ]
    filled = _fill_header_matrix(header, 6)
    assert filled[0] == ["Particulars", "", "2018", "2018", "2019", "2019"]
    assert filled[1] == ["Particulars", "", "Trivandrum", "Kerala", "Trivandrum", "Kerala"]

    resolved = resolve_column_headers(header, 6)
    paths = [c["header_path"] for c in resolved]
    assert paths[0] == ["Particulars"]
    assert paths[1] == [""]
    assert paths[2] == ["2018", "Trivandrum"]
    assert paths[3] == ["2018", "Kerala"]
    assert paths[4] == ["2019", "Trivandrum"]
    assert paths[5] == ["2019", "Kerala"]


def test_none_colspan_still_fills_year_groups():
    rows = [
        ["Block", "Name", "Autumn", None, None, "Winter", None, None],
        [None, None, "Wet", "Dry", "Total", "Wet", "Dry", "Total"],
        ["1", "A", "0", "0", "0", "1", "0", "1"],
        ["2", "B", "0", "0", "0", "1", "0", "1"],
        ["3", "C", "0", "0", "0", "1", "0", "1"],
    ]
    df = dataframe_from_extracted_rows(rows)
    paths = [m.get("header_path") for m in (df.attrs.get("dhara_column_meta") or [])]
    assert paths[2:5] == [["Autumn", "Wet"], ["Autumn", "Dry"], ["Autumn", "Total"]]
    assert paths[5:7] == [["Winter", "Wet"], ["Winter", "Dry"]]
    assert list(df.iloc[0, :2]) == ["1", "A"]
