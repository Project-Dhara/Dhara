"""In-grid captions: TABLE id + main title + scope subtitle (RELIGION-*)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import (
    _is_in_grid_subtitle,
    dataframe_from_extracted_rows,
    extract_in_grid_caption,
)


def _b15_rows(subtitle: str):
    return [
        ["TABLE: B-15"] + [None] * 11,
        ["LIVE BIRTHS BY AGE OF THE MOTHER, BIRTH ORDER AND RELIGION OF THE FAMILY(ALL)"]
        + [None] * 11,
        [None, subtitle] + [None] * 10,
        ["Sl.No.", "MOTHER AGE", "BIRTH ORDER"] + [None] * 8 + ["All"],
        [None, None, "1", "2", "3", "4", "5", "6", "7", "8", ">8", None],
        ["1", "< 15", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
    ]


def test_religion_others_is_subtitle():
    assert _is_in_grid_subtitle("RELIGION-OTHERS")
    assert _is_in_grid_subtitle("RELIGION-ALL")
    assert _is_in_grid_subtitle("RELIGION-HINDU")
    assert _is_in_grid_subtitle("URBAN")
    assert not _is_in_grid_subtitle("Sl.No.")
    assert not _is_in_grid_subtitle("TABLE: B-15")


def test_caption_joins_third_row_religion_subtitle():
    cap = extract_in_grid_caption(_b15_rows("RELIGION-OTHERS"))
    assert cap["table_id_label"] == "TABLE: B-15"
    assert cap["title"] is not None
    assert "LIVE BIRTHS BY AGE OF THE MOTHER" in cap["title"]
    assert "RELIGION-OTHERS" in cap["title"]
    assert " — " in cap["title"]
    # Consume id + main title + subtitle (rows 0..2).
    assert cap["rows_consumed"] == 3


def test_caption_joins_religion_all_subtitle():
    cap = extract_in_grid_caption(_b15_rows("RELIGION-ALL"))
    assert cap["title"].endswith("RELIGION-ALL") or "RELIGION-ALL" in cap["title"]


def test_dataframe_attrs_include_subtitle():
    df = dataframe_from_extracted_rows(_b15_rows("RELIGION-OTHERS"))
    title = (getattr(df, "attrs", {}) or {}).get("dhara_table_caption") or ""
    assert "RELIGION-OTHERS" in title
    assert (getattr(df, "attrs", {}) or {}).get("dhara_banner_table_id") == "TABLE: B-15"
