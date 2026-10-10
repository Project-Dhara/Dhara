"""Blank/dash TOTAL columns must rebuild from denser ruled candidates."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.alignment import (
    _apply_column_alignment_guard,
    _detect_column_alignment_issues,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import (
    _is_row_label_stub_column,
    _structural_bucket_for_df,
    classify_page,
)


def _literacy_df():
    rows = [
        ["1", "272", "60", "197", "573", "439", "27", "1568"],
        ["2", "263", "34", "213", "603", "343", "36", "1492"],
        ["3", "139", "36", "130", "209", "55", "11", "580"],
        ["4", "59", "3", "25", "29", "6", "2", "124"],
        ["5", "12", "1", "6", "3", "1", "0", "23"],
        ["6", "3", "0", "1", "1", "0", "1", "6"],
        ["7", "1", "0", "0", "0", "0", "1", "2"],
        ["8", "1", "0", "0", "0", "0", "1", "2"],
        ["9", "0", "0", "0", "0", "0", "0", "0"],
        ["10", "0", "0", "0", "0", "0", "0", "0"],
        ["above10", "0", "0", "0", "0", "0", "0", "0"],
        ["Not stated", "4", "2", "9", "4", "0", "2", "21"],
        ["TOTAL", "491", "63", "390", "1796", "1010", "68", "3818"],
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "BIRTH ORDER",
            "Illiterate",
            "Below Primary",
            "Primary but Below Matric",
            "Matric but below Graduate",
            "Graduate and above",
            "Not Stated",
            "TOTAL",
        ],
    )


def test_birth_order_stub_is_not_mixed_type():
    vals = ["1", "2", "3", "10", "above10", "Not stated", "TOTAL"]
    assert _is_row_label_stub_column(vals)


def test_literacy_table_auto_accepts_high_confidence():
    df = _literacy_df()
    bucket, reason, info = _structural_bucket_for_df(df)
    assert bucket == "high", (bucket, reason, info)
    assert info.get("mixed_type_columns", 0) == 0


def test_dashed_total_column_detected_and_rebuilt():
    df = _literacy_df()
    # LLM wiped TOTAL to em-dashes (matches Preview uncertainty case).
    sparse_rows = []
    for row in df.values.tolist():
        r = [None if v is None else str(v) for v in row]
        r[-1] = "—"
        sparse_rows.append(r)
    table = {
        "title": "Levels of Literacy by Birth Order",
        "columns": [{"name": c} for c in df.columns],
        "rows": sparse_rows,
        "notes": [],
        "uncertain_cells": [],
        "classification": {},
    }
    issues = _detect_column_alignment_issues(table["columns"], table["rows"])
    assert any(
        i.get("pattern") == "empty_measure" and "total" in str(i.get("name") or "").lower()
        for i in issues
    )
    candidates = [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 400, 400]}]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
    totals = [str(r[-1]).strip() for r in (out.get("rows") or [])]
    assert totals[0] == "1568"
    assert totals[-1] == "3818"
    assert not any(
        isinstance(u, str) and u.lower().startswith("blank value column")
        for u in (out.get("uncertain_cells") or [])
    )


def test_classify_page_high_for_literacy_candidate():
    df = _literacy_df()
    bucket, reason, _ = classify_page(
        [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 100, 100]}]
    )
    assert bucket == "high", (bucket, reason)
