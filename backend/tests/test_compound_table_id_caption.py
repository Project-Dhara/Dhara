"""Compound TABLE ids + comma-heavy CRS captions must stay as in-grid titles."""

from __future__ import annotations

from app.services.extraction.pdf.utils.caption import (
    _is_descriptive_in_grid_title,
    _is_table_id_only,
    _looks_like_column_list_banner,
    extract_in_grid_caption,
)


_A1_TITLE = (
    "POPULATION, REGISTRATION UNITS, MONTHLY RETURNS DUE AND RECEIVED "
    "(RURAL & URBAN)"
)


def _banner_row(text: str, n: int = 7):
    return [text] + [None] * (n - 1)


def test_compound_table_id_is_id_only():
    assert _is_table_id_only("TABLE : A-1 & A-2")
    assert _is_table_id_only("TABLE: A-1 & A-2")
    assert _is_table_id_only("TABLE A-1 and A-2")
    assert not _is_table_id_only(_A1_TITLE)


def test_comma_crs_caption_is_not_column_list():
    assert not _looks_like_column_list_banner(_A1_TITLE)
    assert _is_descriptive_in_grid_title(_A1_TITLE)
    # Still reject true short field-list banners.
    assert _looks_like_column_list_banner("Scheme name, beneficiaries, budget")


def test_extract_a1_a2_population_caption():
    rows = [
        _banner_row("TABLE : A-1 & A-2"),
        _banner_row(_A1_TITLE),
        [
            "Sl. No.",
            "LOCAL BODY",
            "Population -2011",
            "No. of Registration Unit",
            "No. of monthly Returns Due",
            "Total",
            "Adjusted for Incomplete Receipts or Returns",
        ],
        [1, 2, 3, 4, 5, 7, 8],
        ["1", "MCD(U)", "11034555", "112", "1344", "11234567", "11200000"],
    ]
    cap = extract_in_grid_caption(rows)
    assert cap["table_id_label"] == "TABLE : A-1 & A-2"
    assert cap["title"] == _A1_TITLE
    assert cap["rows_consumed"] == 2


def test_extract_a1_a2_merge_filled_banners():
    """Excel-style merge-fill repeats the caption across every column."""
    rows = [
        ["TABLE : A-1 & A-2"] * 7,
        [_A1_TITLE] * 7,
        ["Sl. No.", "LOCAL BODY", "Pop", "Units", "Due", "Total", "Adj"],
        [1, 2, 3, 4, 5, 7, 8],
    ]
    cap = extract_in_grid_caption(rows)
    assert cap["table_id_label"] == "TABLE : A-1 & A-2"
    assert cap["title"] == _A1_TITLE
    assert cap["rows_consumed"] == 2
