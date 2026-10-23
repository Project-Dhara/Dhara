"""Highlights / bullet prose pages must not be kept as tables."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.table_confidence import (
    looks_like_bullet_list_candidate,
)
from app.services.extraction.pdf.utils.pymupdf import filter_candidate_pages


def _highlights_df():
    """Two-column bullet | long sentence — matches CRS Highlights pages."""
    rows = [
        ["►", "The Birth Rate of Kerala is 11.85 in 2022 as against 11.99 in 2021."],
        ["►", "The highest birth rate was reported from Malappuram (15.62) and lowest from Pathanamthitta (7.6)."],
        ["►", "The highest number of births occurred in the month of December (9.24%) and the lowest in February (7.08%)."],
        ["►", "15.87% of Infants reported low birth weight of less than 2.5 kg during 2022 where as it was 14.82% in 2021."],
        ["►", "The number of Deaths registered during the year 2022 is 323929 as against 339648 during 2021."],
        ["►", "The Death Rate of Kerala is 8.52 in 2022 as against 8.97 in 2021."],
        ["►", "The Infant Mortality Rate of Kerala is 5.7 in 2022 as against 5.5 in 2021."],
        ["►", "The Maternal Mortality Ratio of Kerala is 18.55 in 2022 as against 19.0 in 2021."],
    ]
    return pd.DataFrame(rows, columns=["Col_1", "Col_2"])


def test_bullet_highlights_detected():
    hit, reason = looks_like_bullet_list_candidate(_highlights_df())
    assert hit, reason
    assert "prose" in reason or "bullet" in reason


def test_real_stats_table_not_rejected():
    df = pd.DataFrame(
        [
            ["1", "Malappuram", "15.62", "12000"],
            ["2", "Pathanamthitta", "7.60", "3400"],
            ["3", "Thiruvananthapuram", "10.20", "8900"],
            ["4", "Kozhikode", "11.10", "9100"],
            ["5", "Ernakulam", "9.80", "8700"],
        ],
        columns=["S.No.", "District", "Birth Rate", "Births"],
    )
    hit, reason = looks_like_bullet_list_candidate(df)
    assert not hit, reason


def test_filter_candidate_pages_drops_bullet_lists():
    pages = {
        1: [
            {
                "method": "pymupdf_lines_strict",
                "df": _highlights_df(),
                "bbox": [40, 80, 550, 700],
            }
        ],
        2: [
            {
                "method": "pymupdf_lines_strict",
                "df": pd.DataFrame(
                    [["1", "A", "10"], ["2", "B", "20"], ["3", "C", "30"]],
                    columns=["S.No.", "Name", "Count"],
                ),
                "bbox": [40, 80, 550, 400],
            }
        ],
    }
    kept = filter_candidate_pages(pages)
    assert 1 not in kept
    assert 2 in kept
