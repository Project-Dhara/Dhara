"""Bulleted / shaded fact lists must not be promoted as extractable tables."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.table_confidence import (
    looks_like_bullet_list_candidate,
    looks_like_non_table_candidate,
)


def _fact_rows(n: int = 10, bullet: str = "►"):
    templates = [
        "{b} The Projected Mid-year Population of the State in 2022 is 353.69 lakhs "
        "against 351.25 lakhs in 2021 for item {i}.",
        "{b} Sex Ratio at Birth (SRB) in 2022 is 974 against 966 in 2021 for item {i}.",
        "{b} Crude Birth Rate (CBR) declined to 14.2 in 2022 from 14.5 in 2021 for item {i}.",
        "{b} Total Fertility Rate (TFR) is 1.5 in 2022 compared with 1.6 in 2021 for item {i}.",
    ]
    return [templates[i % len(templates)].format(b=bullet, i=i) for i in range(n)]


def test_arrow_bullet_fact_list_is_dropped():
    df = pd.DataFrame({"col0": _fact_rows(12)})
    is_list, reason = looks_like_bullet_list_candidate(df)
    assert is_list, reason
    assert "list" in reason


def test_two_col_bullet_plus_prose_is_dropped():
    rows = _fact_rows(10)
    df = pd.DataFrame({
        "mark": ["►"] * 10,
        "text": [r.replace("► ", "", 1) for r in rows],
    })
    is_list, reason = looks_like_bullet_list_candidate(df)
    assert is_list, reason


def test_wingdings_bullet_fact_list_is_dropped():
    # Private-use bullet glyphs often surface as garbled cells in review.
    df = pd.DataFrame({"col0": _fact_rows(9, bullet="\uf0b7")})
    is_list, reason = looks_like_bullet_list_candidate(df)
    assert is_list, reason


def test_normal_district_stub_table_is_kept():
    df = pd.DataFrame({
        "District": ["Idukki", "Kollam", "Malappuram", "Alappuzha", "Thrissur", "Kozhikode"],
        "Births": [990, 1200, 443032, 2100, 1800, 1600],
        "CBR": [12.1, 13.4, 14.2, 11.8, 12.9, 13.1],
    })
    is_list, reason = looks_like_bullet_list_candidate(df)
    assert not is_list, reason
    is_non, _ = looks_like_non_table_candidate(df)
    assert not is_non


def test_sex_by_age_grid_is_kept():
    cols = ["S.No.", "Disease", "Sex", "<1", "1-4", "5-14", "Total"]
    rows = []
    for i in range(12):
        rows.append([str(i + 1), f"Disease {i}", "M", "1", "2", "3", "6"])
        rows.append(["", "", "F", "1", "1", "2", "4"])
    df = pd.DataFrame(rows, columns=cols)
    is_list, reason = looks_like_bullet_list_candidate(df)
    assert not is_list, reason


def test_non_table_wrapper_still_catches_charts():
    cols = [str(10_000 + i * 17) for i in range(40)]
    df = pd.DataFrame(
        [[str((i * 3 + j) % 10) for j in range(40)] for i in range(4)],
        columns=cols,
    )
    is_non, reason = looks_like_non_table_candidate(df)
    assert is_non
    assert "chart" in reason
