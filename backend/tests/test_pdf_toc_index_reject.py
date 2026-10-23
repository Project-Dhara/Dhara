"""Contents / list-of-tables / index pages must not be kept as data tables."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.table_confidence import (
    looks_like_toc_or_index_candidate,
)
from app.services.extraction.pdf.utils.pymupdf import filter_candidate_pages


def _contents_df():
    return pd.DataFrame(
        [
            ["1", "Introduction", "1"],
            ["2", "Vital Statistics", "15"],
            ["3", "Civil Registration System", "22"],
            ["4", "Annexures and definitions", "40"],
            ["5", "List of officers", "48"],
        ],
        columns=["Sl.No.", "Contents", "Page"],
    )


def _dotted_contents_df():
    return pd.DataFrame(
        [
            ["Introduction .......... 5"],
            ["Vital Statistics ...... 15"],
            ["Civil Registration .... 22"],
            ["Annexures ............. 40"],
            ["Definitions ........... 44"],
        ],
        columns=["Col_1"],
    )


def _births_df():
    return pd.DataFrame(
        [
            ["1", "Malappuram", "15.62", "12000"],
            ["2", "Pathanamthitta", "7.60", "3400"],
            ["3", "Thiruvananthapuram", "10.20", "8900"],
            ["4", "Kozhikode", "11.10", "9100"],
            ["5", "Ernakulam", "9.80", "8700"],
        ],
        columns=["S.No.", "District", "Birth Rate", "Births"],
    )


def _price_index_df():
    return pd.DataFrame(
        [
            ["2019", "112.4"],
            ["2020", "118.1"],
            ["2021", "121.0"],
            ["2022", "130.5"],
        ],
        columns=["Year", "Index"],
    )


def _small_count_df():
    """Long place names and bouncing small counts — not a contents list."""
    return pd.DataFrame(
        [
            ["1", "Thiruvananthapuram", "12"],
            ["2", "Malappuram", "8"],
            ["3", "Kozhikode", "15"],
            ["4", "Ernakulam", "9"],
            ["5", "Kollam", "11"],
        ],
        columns=["S.No.", "District", "Centres"],
    )


def test_contents_grid_detected():
    hit, reason = looks_like_toc_or_index_candidate(_contents_df())
    assert hit, reason


def test_dotted_contents_detected():
    hit, reason = looks_like_toc_or_index_candidate(_dotted_contents_df())
    assert hit, reason


def test_page_text_heading_with_titles_and_pages():
    df = pd.DataFrame(
        [
            ["Overview of the system", "3"],
            ["Registration procedure", "11"],
            ["Birth and death rates", "18"],
            ["District tables", "27"],
        ],
        columns=["Col_1", "Col_2"],
    )
    hit, reason = looks_like_toc_or_index_candidate(df, page_text="CONTENTS\n")
    assert hit, reason


def test_births_table_not_rejected():
    hit, reason = looks_like_toc_or_index_candidate(_births_df())
    assert not hit, reason


def test_price_index_not_rejected():
    hit, reason = looks_like_toc_or_index_candidate(_price_index_df())
    assert not hit, reason


def test_integer_index_scores_not_rejected():
    """A column named Index with score-like integers is not a contents page."""
    df = pd.DataFrame(
        [
            ["Thiruvananthapuram", "112"],
            ["Tamil Nadu", "98"],
            ["Karnataka State", "121"],
            ["Andhra Pradesh", "130"],
        ],
        columns=["State", "Index"],
    )
    hit, reason = looks_like_toc_or_index_candidate(df)
    assert not hit, reason


def test_bouncing_small_counts_not_rejected():
    hit, reason = looks_like_toc_or_index_candidate(_small_count_df())
    assert not hit, reason


def test_filter_candidate_pages_drops_contents():
    pages = {
        1: [{
            "method": "pymupdf_lines_strict",
            "df": _contents_df(),
            "bbox": [40, 80, 550, 700],
        }],
        2: [{
            "method": "pymupdf_lines_strict",
            "df": _births_df(),
            "bbox": [40, 80, 550, 400],
        }],
    }
    kept = filter_candidate_pages(pages)
    assert 1 not in kept
    assert 2 in kept
