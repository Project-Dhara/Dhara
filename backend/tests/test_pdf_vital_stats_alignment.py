"""Vital Statistics / CRS tables: index strip must not force LLM or corrupt values."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.alignment import (
    _apply_column_alignment_guard,
    _count_substantive_data_rows,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import (
    _structural_bucket_for_df,
    classify_page,
    profile_table,
)


def _vital_stats_df():
    """Ruled-candidate shape: 1..8 index strip + 5 bodies + TOTAL."""
    rows = [
        ["1", "2", "3", "4", "5", "6", "7", "8"],
        ["1", "MCD(U)", "12478500", "137", "1644", "0", "NA", None],
        ["2", "NDMC", "302363", "9", "108", "0", "NA", None],
        ["3", "DELHI CANTT", "124917", "1", "12", "0", "NA", None],
        ["4", "TOTAL (URBAN)", "12905780", "147", "1764", "0", "NA", None],
        ["5", "MCD (R)", "944727", "51", "612", "0", "NA", None],
        [None, "TOTAL", "13850507", "198", "2376", "0", "13950000", None],
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "S.No.",
            "Local Body",
            "Population -2001",
            "No. of Registration Unit",
            "No. of monthly Returns Due",
            "No. of Monthly returns not received",
            "Total",
            "Adjusted for Incomplete Receipts or Returns",
        ],
    )


def test_vital_stats_with_index_strip_auto_accepts_high():
    df = _vital_stats_df()
    bucket, reason, info = _structural_bucket_for_df(df)
    assert bucket == "high", (bucket, reason, info)
    assert info.get("mixed_type_columns", 0) == 0
    page_bucket, page_reason, _ = classify_page(
        [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 100, 100]}]
    )
    assert page_bucket == "high", (page_bucket, page_reason)


def test_na_placeholders_do_not_count_as_mixed_type():
    df = _vital_stats_df().iloc[1:].reset_index(drop=True)  # without index strip
    info = profile_table(df)
    assert info["mixed_type_columns"] == 0


def test_swapped_llm_missing_total_rebuilds_from_ruled():
    df = _vital_stats_df()
    # Mimic the broken AI UI: Registration↔not-received swap, 7/8 leak, no TOTAL,
    # trailing dash-only ghost rows.
    sparse = [
        ["1", "2", "3", "4", "5", "6", "7", "8"],
        ["1", "MCD(U)", "12478500", "0", "1644", "137", "7", "8"],
        ["2", "NDMC", "302363", "0", "108", "9", "—", "—"],
        ["3", "DELHI CANTT", "124917", "0", "12", "1", "—", "—"],
        ["4", "TOTAL (URBAN)", "12905780", "0", "1764", "147", "—", "—"],
        ["5", "MCD (R)", "944727", "0", "612", "51", "—", "—"],
        ["—", "—", "—", "—", "—", "—", "—", "—"],
        ["—", "—", "—", "—", "—", "—", "—", "—"],
    ]
    table = {
        "title": "VITAL STATISTICS-2001",
        "columns": [{"name": c} for c in df.columns],
        "rows": sparse,
        "notes": [],
        "uncertain_cells": [],
        "classification": {},
        "semantic_status": "classified",
    }
    assert _count_substantive_data_rows(sparse) < _count_substantive_data_rows(df.values.tolist())
    candidates = [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 400, 400]}]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
    rows = out.get("rows") or []
    # Rebuilt grid keeps index strip + MCD(U) with correct 137 / 0 / NA + TOTAL.
    assert any(
        str(r[1]).strip() == "MCD(U)" and str(r[3]).strip() == "137" and str(r[5]).strip() == "0"
        for r in rows
    )
    assert any(str(r[1]).strip().upper() == "TOTAL" and "13950000" in str(r[6]) for r in rows)
    assert out.get("uncertain_cells"), "fallback must leave a review signal"


def test_swapped_llm_without_ghost_rows_still_rebuilds():
    """Index-echo 7/8 must not inflate fill enough to skip blank-measure restore."""
    df = _vital_stats_df()
    sparse = [
        ["1", "2", "3", "4", "5", "6", "7", "8"],
        ["1", "MCD(U)", "12478500", "0", "1644", "137", "7", "8"],
        ["2", "NDMC", "302363", "0", "108", "9", "—", "—"],
        ["3", "DELHI CANTT", "124917", "0", "12", "1", "—", "—"],
        ["4", "TOTAL (URBAN)", "12905780", "0", "1764", "147", "—", "—"],
        ["5", "MCD (R)", "944727", "0", "612", "51", "—", "—"],
    ]
    table = {
        "title": "VITAL STATISTICS-2001",
        "columns": [{"name": c} for c in df.columns],
        "rows": sparse,
        "notes": [],
        "uncertain_cells": [],
        "classification": {},
        "semantic_status": "classified",
    }
    candidates = [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 400, 400]}]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
    assert any(
        str(r[1]).strip() == "MCD(U)" and str(r[3]).strip() == "137"
        for r in (out.get("rows") or [])
    )
    assert out.get("uncertain_cells")
