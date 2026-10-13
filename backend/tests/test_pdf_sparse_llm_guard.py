"""Sparse LLM reconstructions must rebuild from denser ruled candidates."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.alignment import _apply_column_alignment_guard


def _full_df():
    rows = []
    # Section + intestinal M/F + cholera M/F + typhoid M/F
    rows.append(["I", "CERTAIN INFECTIOUS AND PARASITIC DISEASES (A00-B99)", None, None, None, None])
    rows.append(["1", "INTESTINAL INFECTIOUS DISEASES (A00-A09)", "M", "59", "21", "195"])
    rows.append(["", "", "F", "35", "20", "154"])
    rows.append(["1", "Cholera (A00)", "M", "0", "0", "1"])
    rows.append(["", "", "F", "0", "0", "2"])
    rows.append(["2", "Typhoid Fever and paratyphoid fevers (A01)", "M", "0", "0", "3"])
    rows.append(["", "", "F", "0", "18", "25"])
    df = pd.DataFrame(
        rows,
        columns=["S.No.", "Name of the Disease", "Sex", "<1", "1-4", "Total"],
    )
    df.attrs["dhara_column_meta"] = [
        {"name": n, "header_group": None, "header_path": [n]} for n in df.columns
    ]
    return df


def test_sparse_llm_table_rebuilds_from_ruled_grid():
    # Mimic the broken AI UI: labels present, most body blank, values at end.
    sparse_rows = [
        ["1", "INTESTINAL INFECTIOUS DISEASES", None, None, None, None],
        ["2", "Cholera (A00)", "M", "0", "0", "1"],
        ["", "Typhoid Fever and paratyphoid fevers (A01)", "M", None, None, None],
        ["4", "Food Poisoning (A02, A05)", "M", None, None, None],
        ["5", "Shigellosis (A03)", "M", None, None, None],
        ["", "", "M", None, None, None],
        ["7", "Diarrhoea and gastroenteritis of presumed infectious origin (A09)", "M", None, None, None],
    ]
    # Large hollow middle + crammed trailing values (as in the UI).
    sparse_rows.extend([[None, None, None, None, None, None] for _ in range(30)])
    sparse_rows.append([None, None, None, "0", "18", "25"])

    table = {
        "title": "Medically Certified Deaths",
        "columns": [
            {"name": "S.No."},
            {"name": "Name of the Disease"},
            {"name": "Sex"},
            {"name": "<1"},
            {"name": "1-4"},
            {"name": "Total"},
        ],
        "rows": sparse_rows,
        "notes": [],
        "uncertain_cells": [],
        "classification": {},
    }
    candidates = [
        {
            "method": "pymupdf_lines_strict",
            "df": _full_df(),
            "bbox": [0, 0, 400, 600],
        }
    ]
    out = _apply_column_alignment_guard(table, candidates, used_candidates=set())
    assert (out.get("extraction") or {}).get("confidence") == "alignment_guard_fallback"
    rows = out.get("rows") or []
    assert len(rows) == 7

    def _cell(v):
        if v is None:
            return ""
        s = str(v).strip()
        return "" if s.lower() in ("", "nan", "none") else s

    snos = [_cell(r[0]) for r in rows]
    assert snos[3] == "1"  # Cholera M
    assert snos[4] == ""   # Cholera F
    assert snos[5] == "2"  # Typhoid M
    assert snos[6] == ""   # Typhoid F
    # Values present on F typhoid row, not dumped as a trailing ghost row.
    assert _cell(rows[6][4]) == "18"
    assert _cell(rows[6][5]) == "25"
    assert not any(all(_cell(v) == "" for v in r) for r in rows)
