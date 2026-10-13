"""Titles like TABLE -8 + descriptive line below must surface the description."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.table_confidence import (
    _descriptive_line_after_caption_id,
    _descriptive_line_near_caption_id,
    _is_caption_id_only,
    _is_weak_inferred_title,
    _matches_extended_caption,
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
    assert _is_caption_id_only("TABLE 10(I)")
    assert _is_caption_id_only("TABLE-11(i)")
    assert _is_caption_id_only("TABLE (ii)")
    assert _is_caption_id_only("TABLE - (I)")
    assert _is_caption_id_only("TABLE (viii)")
    assert not _is_caption_id_only(
        "DEATHS BY CAUSE (MEDICALLY CERTIFIED OR OTHERWISE,2001)"
    )


def test_paren_table_ids_match_extended_caption():
    """Vital-stats 'TABLE (ii)' / 'TABLE - (I)' must be recognized as captions."""
    assert _matches_extended_caption("TABLE (ii)")
    assert _matches_extended_caption("TABLE (iii)")
    assert _matches_extended_caption("TABLE (V)")
    assert _matches_extended_caption("TABLE - (I)")
    assert _matches_extended_caption("TABLE 10(I)")
    assert _matches_extended_caption("TABLE-12( iv)")


def test_rejects_total_male_as_title():
    cols = ["S.No.", "Cause of Death", "MALE", "FEMALE"]
    assert _is_weak_inferred_title("TOTAL", cols)
    assert _is_weak_inferred_title("MALE", cols)
    assert _is_weak_inferred_title("TABLE -8", cols)
    assert _is_weak_inferred_title("Months", cols)
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


def test_skips_stub_headers_between_table_id_and_title():
    """Months / Rural stubs between TABLE-11(i) and the real caption."""
    lines = [
        "TABLE-11(i)",
        "Months",
        "Rural",
        "Urban",
        "Total",
        "NUMBER OF LIVE BIRTHS BY MONTH AND SEX -2001",
    ]
    cols = ["Months", "Male", "Female", "Total"]
    desc = _descriptive_line_near_caption_id(lines, 0, cols)
    assert desc and "LIVE BIRTHS BY MONTH" in desc


def test_skips_levels_of_literacy_header_group_for_real_title():
    """In-grid 'LEVELS OF LITERACY' must not beat the caption above the table."""
    lines = [
        "LIVE BIRTH BY BIRTH ORDER & LITERACY OF FATHER, 2001",
        "RURAL",
        "LEVELS OF LITERACY",
        "TABLE-14(ii)",
    ]
    cols = ["BIRTH ORDER", "Illiterate", "TOTAL"]
    title, source, banner = _title_from_page_lines(lines, cols)
    assert title and "LITERACY OF FATHER" in title
    assert "LEVELS OF LITERACY" not in title
    assert "RURAL" in title
    assert banner == "TABLE-14(ii)"


def test_skips_levels_of_education_header_group_prefers_caption():
    lines = [
        "MCD(URBAN)",
        "LIVE BIRTH BY LEVEL OF EDUCATION OF MOTHER AND BIRTH ORDER, 2001",
        "TABLE-13( iv )",
        "LEVELS OF EDUCATION OF MOTHER",
        "BIRTH",
        "ORDER",
    ]
    cols = ["BIRTH ORDER", "Illiterate", "TOTAL"]
    title, source, banner = _title_from_page_lines(lines, cols)
    assert title and "EDUCATION OF MOTHER AND BIRTH ORDER" in title
    assert "LEVELS OF EDUCATION OF MOTHER" != title
    assert "LEVELS OF" not in (title or "").split(" — ")[0]
    assert "MCD" in title or "URBAN" in title
    assert banner == "TABLE-13( iv )"


def test_appends_delhi_cantt_scope_under_caption():
    lines = [
        "TABLE-13( vi )",
        "LIVE BIRTH BY LEVEL OF EDUCATION OF MOTHER AND BIRTH ORDER, 2001",
        "DELHI CANTT.",
    ]
    cols = ["BIRTH ORDER", "Illiterate", "TOTAL"]
    title, source, banner = _title_from_page_lines(lines, cols)
    assert title and "EDUCATION OF MOTHER AND BIRTH ORDER" in title
    assert "DELHI CANTT" in title
    assert banner == "TABLE-13( vi )"


def test_title_above_table_paren_id():
    """Some pages put the descriptive line above TABLE (ii)."""
    lines = [
        "LIVE BIRTHS BY THE TYPE OF ATTENTION AT DELIVERY, 1991 - 2001",
        "DOMICILIARY",
        "TABLE (ii)",
        "YEAR",
        "TOTAL",
    ]
    cols = ["YEAR", "TOTAL", "RURAL"]
    title, source, banner = _title_from_page_lines(lines, cols)
    assert title and "ATTENTION AT DELIVERY" in title
    assert banner == "TABLE (ii)"
    assert "caption" in source


def test_table_paren_i_finds_vital_statistics_title():
    lines = [
        "VITAL STATISTICS BY SEX, 1991 - 2001",
        "TABLE - (I)",
        "YEAR",
        "LIVE BIRTHS",
    ]
    cols = ["YEAR", "MALE", "FEMALE", "TOTAL"]
    title, source, banner = _title_from_page_lines(lines, cols)
    assert title and "VITAL STATISTICS" in title
    assert banner == "TABLE - (I)"


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
