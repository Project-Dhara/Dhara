"""Missing-row / rebuild guard: no false positives or false negatives."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.alignment import (
    _apply_column_alignment_guard,
    _uncertain_note_is_alignment_mismatch,
)
from app.services.extraction.pdf.confidence_validation.normalize import (
    derive_human_review_needed,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import (
    table_dict_from_df,
)


def _season_paddy_df() -> pd.DataFrame:
    """4-row ruled grid: seasons + All seasons summary (1822-213 style)."""
    return pd.DataFrame(
        [
            ["Autumn", "50,460.07", "44,844.20", "-11.13%", "1,37,051.8", "1,16,269.4", "-15.16%"],
            ["Winter", "71,429.82", "72,107.19", "0.95%", "2,24,928.2", "2,12,261.9", "-5.63%"],
            ["Summer", "69,822.27", "63,327.10", "-9.30%", "2,33,880.4", "2,04,795.8", "-12.44%"],
            ["All seasons", "1,91,712.16", "1,80,278.49", "-5.96%", "5,95,860.3", "5,33,327.1", "-10.49%"],
        ],
        columns=[
            "Season",
            "2022-23",
            "2023-24",
            "% of variation",
            "2022-23 (2)",
            "2023-24 (2)",
            "% of variation (2)",
        ],
    )


def _measure_table(df: pd.DataFrame) -> dict:
    table = table_dict_from_df(df.copy(), method="llm")
    for col in table["columns"][1:]:
        col["role"] = "measure"
        col["data_type"] = "number"
    table["semantic_status"] = "classified"
    table["classification"] = {}
    table["title"] = "Area and Production of Rice"
    return table


def test_missing_rows_rebuild_clears_review_when_grid_is_complete():
    """LLM dropped Summer/All seasons; rebuild restores them — no stale review flag."""
    df = _season_paddy_df()
    table = _measure_table(df.iloc[:2])
    candidates = [
        {"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 400, 200]},
        {
            "method": "pymupdf_lines_strict",
            "df": pd.DataFrame([[None, "48.197", "46.9"], [None, None, "17.1"]]),
            "bbox": [0, 0, 50, 50],
        },
    ]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
    labels = [str(r[0]).strip() for r in (out.get("rows") or [])]
    assert labels == ["Autumn", "Winter", "Summer", "All seasons"]
    uncertain = out.get("uncertain_cells") or []
    assert not any(_uncertain_note_is_alignment_mismatch(u) for u in uncertain), uncertain
    needed, reason = derive_human_review_needed(out)
    assert reason != "column_alignment_mismatch", (needed, reason, uncertain)


def test_summary_row_only_drop_is_detected_and_rebuilt():
    """FN guard: dropping only 'All seasons' (3 vs 4) must rebuild."""
    df = _season_paddy_df()
    table = _measure_table(df.iloc[:3])
    candidates = [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 400, 200]}]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
    labels = [str(r[0]).strip() for r in (out.get("rows") or [])]
    assert "All seasons" in labels
    assert len(labels) == 4
    # Clean rebuild → no alignment Needs Review
    uncertain = out.get("uncertain_cells") or []
    assert not any(_uncertain_note_is_alignment_mismatch(u) for u in uncertain), uncertain


def test_complete_season_table_not_flagged():
    """Already-complete LLM grid must not invent a missing-rows issue."""
    df = _season_paddy_df()
    table = _measure_table(df)
    candidates = [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 400, 200]}]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") != "alignment_guard_fallback"
    assert not (out.get("uncertain_cells") or [])


def test_unrelated_wider_table_on_page_does_not_steal_season_grid():
    """FP guard: complete 7-col table must not rebuild into an unrelated 15-col grid."""
    df = _season_paddy_df()
    table = _measure_table(df)
    wide = pd.DataFrame(
        [[str(i)] + [str(i * j) for j in range(14)] for i in range(10)],
        columns=[str(c) for c in range(15)],
    )
    candidates = [
        {"method": "pymupdf_lines_strict", "df": wide, "bbox": [0, 0, 500, 500]},
        {"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 400, 200]},
    ]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") != "alignment_guard_fallback"
    assert len(out.get("columns") or []) == 7
    labels = [str(r[0]).strip() for r in (out.get("rows") or [])]
    assert labels[0] == "Autumn"
    assert not any(
        _uncertain_note_is_alignment_mismatch(u) for u in (out.get("uncertain_cells") or [])
    )


def test_missing_rows_rebuild_uses_same_width_not_wider_sibling():
    """When rows are missing, rebuild from the 7-col season grid — not the 15-col sibling."""
    df = _season_paddy_df()
    table = _measure_table(df.iloc[:2])
    wide = pd.DataFrame(
        [[str(i)] + [str(i * j) for j in range(14)] for i in range(10)],
        columns=[str(c) for c in range(15)],
    )
    candidates = [
        {"method": "pymupdf_lines_strict", "df": wide, "bbox": [0, 0, 500, 500]},
        {"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 400, 200]},
    ]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
    assert len(out.get("columns") or []) == 7
    labels = [str(r[0]).strip() for r in (out.get("rows") or [])]
    assert labels == ["Autumn", "Winter", "Summer", "All seasons"]
