"""Chart/figure regions must not be promoted as extractable tables."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.table_confidence import looks_like_chart_candidate


def test_wide_numeric_crumb_grid_is_chart():
    # Mimic Graph No. 4 false positive: few rows, dozens of numeric "headers".
    cols = [str(10_000 + i * 17) for i in range(40)]
    df = pd.DataFrame(
        [[str((i * 3 + j) % 10) for j in range(40)] for i in range(4)],
        columns=cols,
    )
    is_chart, reason = looks_like_chart_candidate(df)
    assert is_chart
    assert "chart-like grid" in reason


def test_normal_year_rate_table_is_not_chart():
    df = pd.DataFrame(
        {
            "Year": [1991, 1992, 1993, 1994, 1995, 1996],
            "Death Rate * (Per thousand population)": [6.35, 6.23, 6.20, 6.34, 6.21, 6.55],
            "Year (2)": [1997, 1998, 1999, 2000, 2001, None],
            "Death Rate (Per thousand population)": [5.90, 6.43, 6.06, 5.93, 5.81, None],
        }
    )
    is_chart, reason = looks_like_chart_candidate(df)
    assert not is_chart
    assert reason == ""


def test_cause_of_death_style_grid_is_not_chart():
    cols = [
        "S.No.", "Name of the Disease", "Sex",
        "<1", "1-4", "5-14", "15-24", "25-34", "35-44",
        "45-54", "55-64", "65-69", ">=70", "Not stated", "Total",
    ]
    rows = []
    for i in range(20):
        rows.append(
            [str(i + 1), f"Disease {i}", "M"] + [str(j) for j in range(11)] + ["10"]
        )
        rows.append(
            ["", "", "F"] + [str(j) for j in range(11)] + ["8"]
        )
    df = pd.DataFrame(rows, columns=cols)
    is_chart, reason = looks_like_chart_candidate(df)
    assert not is_chart
    assert reason == ""
