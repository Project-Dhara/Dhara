"""Titles like TABLE -8 + descriptive line below must surface the description."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from extraction.pdf_table_confidence import (
    _descriptive_line_after_caption_id,
    _is_caption_id_only,
    _is_weak_inferred_title,
    _title_from_page_lines,
    infer_title_from_page_text,
    infer_title_meta_from_page_text,
    table_dict_from_df,
)
import pandas as pd


def test_table_dash_number_is_caption_id_only():
    assert _is_caption_id_only("TABLE -8")
    assert _is_caption_id_only("TABLE-8")
    assert _is_caption_id_only("Table -9")
    assert _is_caption_id_only("TABLE: B-22")
    assert not _is_caption_id_only(
        "DEATHS BY CAUSE (MEDICALLY CERTIFIED OR OTHERWISE,2001)"
    )


def test_rejects_total_male_as_title():
    cols = ["S.No.", "Cause of Death", "MALE", "FEMALE"]
    assert _is_weak_inferred_title("TOTAL", cols)
    assert _is_weak_inferred_title("MALE", cols)
    assert _is_weak_inferred_title("TABLE -8", cols)
    assert not _is_weak_inferred_title(
        "DEATHS BY CAUSE (MEDICALLY CERTIFIED OR OTHERWISE,2001)", cols
    )


def test_descriptive_line_under_table_id():
    lines = [
        "Some chrome",
        "TABLE -8",
        "DEATHS BY CAUSE (MEDICALLY CERTIFIED OR OTHERWISE,2001)",
        "S.No.",
        "Cause of Death",
    ]
    cols = ["S.No.", "Cause of Death", "MALE", "FEMALE"]
    desc = _descriptive_line_after_caption_id(lines, 1, cols)
    assert desc and "DEATHS BY CAUSE" in desc


def test_page_lines_prefer_description_under_table_id():
    lines = [
        "TABLE -8",
        "DEATHS BY CAUSE (MEDICALLY CERTIFIED OR OTHERWISE,2001)",
        "S.No. Cause of Death MALE FEMALE",
    ]
    cols = ["S.No.", "Cause of Death", "MALE", "FEMALE"]
    title, source, banner = _title_from_page_lines(lines, cols)
    assert title and "DEATHS BY CAUSE" in title
    assert banner == "TABLE -8"
    assert "below_id" in source


def test_infer_title_skips_weak_bbox_heading_for_page_caption():
    page_text = "\n".join([
        "TABLE -8",
        "DEATHS BY CAUSE (MEDICALLY CERTIFIED OR OTHERWISE,2001)",
        "Cause of Death",
        "MALE",
    ])
    cols = ["S.No.", "Cause of Death", "MALE", "FEMALE"]
    # Fake bbox blocks that previously caused TOTAL to win.
    blocks = [
        {"text": "TOTAL", "x0": 100, "y0": 100, "x1": 140, "y1": 120},
        {"text": "8", "x0": 100, "y0": 130, "x1": 110, "y1": 140},
    ]
    bbox = [100.0, 150.0, 700.0, 500.0]
    title, source = infer_title_from_page_text(
        page_text, cols, 46, bbox=bbox, page_blocks=blocks
    )
    assert title and "DEATHS BY CAUSE" in title
    assert source != "heuristic_bbox_heading"
    _t, _s, banner = infer_title_meta_from_page_text(
        page_text, cols, 46, bbox=bbox, page_blocks=blocks
    )
    assert banner == "TABLE -8"


def test_table_dict_stores_banner_and_descriptive_title():
    df = pd.DataFrame(
        [["1", "Cholera", "6", "2"]],
        columns=["S.No.", "Cause of Death", "MALE", "FEMALE"],
    )
    page_text = "\n".join([
        "TABLE -8",
        "DEATHS BY CAUSE (MEDICALLY CERTIFIED OR OTHERWISE,2001)",
        "S.No.",
    ])
    out = table_dict_from_df(df, page_text=page_text, page_num=46)
    assert out["title"] and "DEATHS BY CAUSE" in out["title"]
    assert out.get("banner_table_id") == "TABLE -8"
