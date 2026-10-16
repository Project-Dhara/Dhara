"""Dedupe must prefer clean lines_strict grids over phantom-inflated lines."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from app.services.extraction.pdf.utils.pymupdf import (
    _is_substantially_richer,
    _substantive_column_count,
    dedupe_candidates_by_bbox,
)


def _df_with_meta(columns, paths, rows):
    df = pd.DataFrame(rows, columns=columns)
    df.attrs["dhara_column_meta"] = [
        {"name": columns[i], "header_path": paths[i], "header_group": None}
        for i in range(len(columns))
    ]
    return df


def test_substantive_count_ignores_index_leaf_phantoms():
    clean = _df_with_meta(
        ["District", "Forest", "Cultivable waste"],
        [["District"], ["Forest"], ["Cultivable waste"]],
        [["Kollam", "81438", "2230.8"]],
    )
    messy = _df_with_meta(
        ["District", "2", "Forest", "4", "Cultivable waste", "9"],
        [
            ["District"],
            ["District", "2"],
            ["Forest"],
            ["Forest", "4"],
            ["Cultivable waste"],
            ["Cultivable waste", "9"],
        ],
        [["Kollam", None, "81438", None, "2230.8", "0"]],
    )
    assert _substantive_column_count(clean) == 3
    assert _substantive_column_count(messy) == 3


def test_phantom_inflated_lines_not_richer_than_lines_strict():
    strict = {
        "method": "pymupdf_lines_strict",
        "bbox": [0, 0, 100, 100],
        "df": _df_with_meta(
            ["Sl. No", "District", "Forest", "Cultivable waste"],
            [["Sl. No"], ["District"], ["Forest"], ["Cultivable waste"]],
            [
                ["1", "Thiruvananthapuram", "49861", "920.86"],
                ["2", "Kollam", "81438", "2230.8"],
            ],
        ),
    }
    loose = {
        "method": "pymupdf_lines",
        "bbox": [0, 0, 100, 100],
        "df": _df_with_meta(
            ["Sl. No", "1", "District", "2", "Forest", "4", "Cultivable waste", "9"],
            [
                ["Sl. No"],
                ["Sl. No", "1"],
                ["District"],
                ["District", "2"],
                ["Forest"],
                ["Forest", "4"],
                ["Cultivable waste"],
                ["Cultivable waste", "9"],
            ],
            [
                ["1", None, "Thiruvananthapuram", None, "49861", None, "920.86", None],
                ["2", None, "Kollam", None, "81438", None, "2230.8", None],
            ],
        ),
    }
    assert not _is_substantially_richer(loose, strict)
    kept = dedupe_candidates_by_bbox([strict, loose])
    assert len(kept) == 1
    assert kept[0]["method"] == "pymupdf_lines_strict"


def test_real_fragment_lines_strict_still_loses_to_full_grid():
    """Stub-only lines_strict must not eclipse a real wider lines table."""
    stub = {
        "method": "pymupdf_lines_strict",
        "bbox": [0, 0, 40, 100],
        "df": _df_with_meta(
            ["Sl. No", "District"],
            [["Sl. No"], ["District"]],
            [["1", "Kollam"], ["2", "Idukki"]],
        ),
    }
    full = {
        "method": "pymupdf_lines",
        "bbox": [0, 0, 100, 100],
        "df": _df_with_meta(
            ["Sl. No", "District", "Jan", "Feb", "Mar", "Apr", "May"],
            [["Sl. No"], ["District"], ["Jan"], ["Feb"], ["Mar"], ["Apr"], ["May"]],
            [
                ["1", "Kollam", "1", "2", "3", "4", "5"],
                ["2", "Idukki", "6", "7", "8", "9", "10"],
            ],
        ),
    }
    assert _is_substantially_richer(full, stub)
    kept = dedupe_candidates_by_bbox([stub, full])
    assert kept[0]["method"] == "pymupdf_lines"
