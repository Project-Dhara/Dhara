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


def test_line_chart_percent_label_strip_is_chart():
    # Graph point labels misread as a 1×N table (54%, 57%, …).
    cols = ["54%", "57%", "54% (3)", "56%", "60%", "67%", "81%", "75%", "71%", "79%"]
    df = pd.DataFrame([["41%"] + [None] * 9], columns=cols)
    is_chart, reason = looks_like_chart_candidate(df)
    assert is_chart, reason
    assert "label" in reason or "percent" in reason


def test_bar_chart_uniquified_numeric_headers_with_fat_rects_is_chart():
    # Bar value crumbs become 381 / 381 (2) / … after pandas uniquify.
    cols = ["76.57", "174.82", "286.62"] + [f"381 ({i})" for i in range(2, 8)]
    df = pd.DataFrame(
        [
            [".82", "28", "6", None, None, None, "37", None, None],
            [None, None, None, None, None, None, None, None, None],
            [None, "64", None, None, None, None, None, None, None],
            [None, None, None, None, None, None, None, None, None],
        ],
        columns=cols,
    )

    class _Rect:
        def __init__(self, x0, y0, x1, y1):
            self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
            self.width = x1 - x0
            self.height = y1 - y0

    class _Page:
        def get_drawings(self):
            # Tall thin bars inside the candidate bbox.
            return [
                {"rect": _Rect(20 + i * 30, 40, 35 + i * 30, 200)}
                for i in range(10)
            ]

        def get_text(self, *args, **kwargs):
            return "Area of Ginger 2023-24 (in Ha)"

    is_chart, reason = looks_like_chart_candidate(
        df, page=_Page(), bbox=[0, 0, 400, 300],
    )
    assert is_chart, reason
