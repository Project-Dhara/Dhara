"""Trailing dash-only rows must not force review or survive cleaning."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.confidence_validation.normalize import _normalize_table
from app.services.extraction.pdf.confidence_validation.stamp import _stamp_llm_metadata
from app.services.extraction.pdf.confidence_validation.table_confidence import (
    _drop_trailing_placeholder_rows,
    _is_identity_stub_column,
    _structural_bucket_for_df,
    clean_dataframe_light,
    classify_page,
    sanitize_table_trailing_placeholders,
    strip_trailing_placeholder_rows,
    table_dict_from_df,
)


def _paddy_footer_df():
    """Block mixes serials + * Total labels — previously flagged as murky mix."""
    rows = [
        ["THIRUVANANTHAPURAM", None, None, None, None, None],
        ["1", "Edava", "7.80", "0", "7.80", "16.30"],
        ["2", "Elekamon", "56.03", "0", "56.03", "117.85"],
        ["3", "Cherunniyoor", "13.28", "0", "13.28", "25.58"],
        ["Varkala Total", None, "217.17", "0", "217.17", "398.71"],
        ["1", "Poovachal", "0.00", "0", "0.00", "0.00"],
        ["8", "Kattakada", "0.04", "0", "0.04", "0.04"],
        ["Vellanad Total", None, "0.18", "0.041", "0.22", "1.43"],
        ["Blocks Total", None, "667.6", "0.045", "667.65", "1295.15"],
        ["Municipality Total", None, "3.13", "0", "3.13", "3.22"],
        ["Corporation Total", None, "11.33", "0.983", "12.31", "27.20"],
        ["District Total", None, "682.06", "1.028", "683.09", "1325.57"],
    ]
    return pd.DataFrame(
        rows,
        columns=["Block", "Panchayat", "Wet", "Dry", "Total", "Grand Total"],
    )


def test_block_serial_and_totals_is_identity_stub():
    vals = [
        "THIRUVANANTHAPURAM",
        "1",
        "2",
        "3",
        "Varkala Total",
        "8",
        "Blocks Total",
        "District Total",
    ]
    assert _is_identity_stub_column(vals)


def test_measure_column_with_spill_is_not_identity_stub():
    vals = ["7.80", "56.03", "0.00", "Athiyanoor", "11.33", "682.06"]
    assert not _is_identity_stub_column(vals)


def test_paddy_footer_auto_accepts_without_llm():
    df = _paddy_footer_df()
    bucket, reason, info = _structural_bucket_for_df(df)
    assert bucket == "high", (bucket, reason, info)
    assert info.get("mixed_type_columns", 0) == 0
    page_bucket, page_reason, _ = classify_page(
        [{"method": "pymupdf_lines_strict", "df": df, "bbox": [0, 0, 100, 100]}]
    )
    assert page_bucket == "high", (page_bucket, page_reason)


def test_trailing_dash_rows_stripped_from_dataframe():
    df = _paddy_footer_df()
    ghost = pd.DataFrame(
        [["-"] * 6 for _ in range(12)],
        columns=df.columns,
    )
    padded = pd.concat([df, ghost], ignore_index=True)
    cleaned = clean_dataframe_light(padded)
    assert len(cleaned) == len(df)
    assert str(cleaned.iloc[-1, 0]) == "District Total"
    # Mid-table dash row is preserved (not trailing).
    mid = df.copy()
    mid.loc[3] = ["-", "-", "-", "-", "-", "-"]
    mid_out = _drop_trailing_placeholder_rows(mid)
    assert len(mid_out) == len(mid)


def test_normalize_table_drops_trailing_dash_ghosts():
    table = {
        "title": "PANCHAYATH WISE PADDY AREA",
        "columns": [{"name": c} for c in ["Block", "Wet", "Dry"]],
        "rows": [
            ["Corporation Total", "11.33", "0.983"],
            ["District Total", "682.06", "1.028"],
            ["-", "-", "-"],
            ["—", "—", "—"],
            ["-", "-", "-"],
        ],
        "notes": [],
        "uncertain_cells": [],
        "classification": {},
    }
    out = _normalize_table(table)
    assert len(out["rows"]) == 2
    assert out["rows"][-1][0] == "District Total"


def test_table_dict_from_df_has_no_trailing_placeholders():
    df = _paddy_footer_df()
    for _ in range(8):
        df = pd.concat(
            [df, pd.DataFrame([["-"] * len(df.columns)], columns=df.columns)],
            ignore_index=True,
        )
    table = table_dict_from_df(df)
    rows = table["rows"]
    assert rows[-1][0] == "District Total"
    assert not all(str(v).strip() in {"-", "—", "–", ""} for v in rows[-1] if v is not None)


def test_strip_helper_only_trims_trailing_run():
    rows = [
        ["A", "1"],
        ["-", "-"],
        ["B", "2"],
        ["-", "-"],
        ["—", "—"],
    ]
    out = strip_trailing_placeholder_rows(rows)
    assert out == [["A", "1"], ["-", "-"], ["B", "2"]]


def test_stamp_final_gate_strips_ghosts_reintroduced_after_normalize():
    """Attach/restore can put dash rows back; stamp must strip before review."""
    page_result = {
        "tables": [
            {
                "title": "PANCHAYATH WISE PADDY AREA",
                "columns": [{"name": "Block"}, {"name": "Wet"}, {"name": "Dry"}],
                "rows": [
                    ["Corporation Total", "11.33", "0.983"],
                    ["District Total", "682.06", "1.028"],
                    ["-", "-", "-"],
                    ["-", "-", "-"],
                    ["—", "—", "—"],
                ],
                "notes": [],
                "uncertain_cells": [],
                "classification": {},
            }
        ]
    }
    out = _stamp_llm_metadata(page_result, page_num=1, candidates=[], page_text="")
    tables = out["tables"]
    assert len(tables) == 1
    rows = tables[0]["rows"]
    assert len(rows) == 2
    assert rows[-1][0] == "District Total"
    # Ghost dash rows are gone even if semantic review still applies.
    assert not any(
        all(str(c).strip() in {"-", "—", "–", ""} for c in row)
        for row in rows
    )


def test_sanitize_table_is_idempotent():
    table = {
        "rows": [
            ["District Total", "1", "2"],
            ["-", "-", "-"],
        ]
    }
    sanitize_table_trailing_placeholders(table)
    sanitize_table_trailing_placeholders(table)
    assert table["rows"] == [["District Total", "1", "2"]]
