"""LLM dropping S.No./Name stubs must rebuild from the full ruled grid."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.alignment import _apply_column_alignment_guard
from app.services.extraction.pdf.utils.pymupdf import (
    _llm_missing_identity_stubs,
    _llm_starts_at_sex_column,
    _score_candidate_for_table_shape,
)


def _stub_df():
    df = pd.DataFrame(
        [
            ["I", "CERTAIN INFECTIOUS AND PARASITIC DISEASES (A00-B99)", None, None, None],
            ["1", "INTESTINAL INFECTIOUS DISEASES (A00-A09)", "M", "59", "195"],
            ["", "", "F", "35", "154"],
            ["1", "Cholera (A00)", "M", "0", "1"],
            ["", "", "F", "0", "2"],
        ],
        columns=["S.No.", "Name of the Disease", "Sex", "<1", "Total"],
    )
    df.attrs["dhara_column_meta"] = [
        {"name": n, "header_group": None, "header_path": [n]} for n in df.columns
    ]
    return df


def _fragment_df():
    # LLM-shaped fragment: stubs dropped, starts at Sex.
    df = pd.DataFrame(
        [
            ["M", "59", "195"],
            ["F", "35", "154"],
            ["M", "0", "1"],
            ["F", "0", "2"],
        ],
        columns=["Sex", "<1", "Total"],
    )
    df.attrs["dhara_column_meta"] = [
        {"name": n, "header_group": None, "header_path": [n]} for n in df.columns
    ]
    return df


def test_llm_starts_at_sex_detected():
    assert _llm_starts_at_sex_column([{"name": "Sex"}, {"name": "<1"}])
    assert not _llm_starts_at_sex_column([{"name": "S.No."}, {"name": "Sex"}])


def test_missing_identity_stubs_detected():
    table = {
        "columns": [{"name": "Sex"}, {"name": "<1"}, {"name": "Total"}],
        "rows": [["M", "59", "195"]],
    }
    cand = {"method": "pymupdf_lines_strict", "df": _stub_df()}
    assert _llm_missing_identity_stubs(table, cand)


def test_shape_score_prefers_full_grid_when_stubs_dropped():
    table = {
        "columns": [{"name": "Sex"}, {"name": "<1"}, {"name": "Total"}],
        "rows": [["M", "59", "195"], ["F", "35", "154"]],
    }
    full = {"method": "pymupdf_lines_strict", "df": _stub_df()}
    frag = {"method": "pymupdf_lines_strict", "df": _fragment_df()}
    assert _score_candidate_for_table_shape(table, full) > _score_candidate_for_table_shape(
        table, frag
    )


def test_alignment_guard_rebuilds_when_sno_name_dropped():
    table = {
        "title": "Medically Certified Deaths",
        "columns": [
            {"name": "Sex", "role": "dimension"},
            {"name": "<1", "role": "measure"},
            {"name": "Total", "role": "measure"},
        ],
        "rows": [
            ["M", "59", "195"],
            ["F", "35", "154"],
        ],
        "notes": [],
        "uncertain_cells": [],
        "classification": {},
    }
    candidates = [
        {"method": "pymupdf_lines_strict", "df": _fragment_df(), "bbox": [0, 0, 100, 100]},
        {"method": "pymupdf_lines_strict", "df": _stub_df(), "bbox": [0, 0, 200, 200]},
    ]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    names = [c.get("name") for c in out.get("columns") or []]
    assert any(n and "S.No" in str(n) for n in names) or any(
        n and "Name" in str(n) for n in names
    )
    assert len(out.get("columns") or []) >= 5
    assert (out.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
    # Section banner / first labelled row preserved from ruled grid.
    rows = out.get("rows") or []
    assert any(
        row and any(v and "INFECTIOUS" in str(v).upper() for v in row)
        for row in rows
    )
