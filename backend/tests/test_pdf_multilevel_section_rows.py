"""Season groups stay nested, and in-body section rows are kept.

Panchayat-wise area tables use a two-level header (Autumn / Wet, Dry, Total)
plus a district band (THIRUVANANTHAPURAM) that spans the grid with no measures.
A looser ruled extract bisects those columns; that wider grid must not replace
the real header, and the district band must stay in the body.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows
from app.services.extraction.pdf.utils.pymupdf import (
    _is_substantially_richer,
    dedupe_candidates_by_bbox,
)


def _strict_paddy_rows():
    return [
        ["TABLE - 3.1"] + [None] * 11,
        ["PANCHAYATH WISE PADDY AREA 2023-24 UNIT:- Ha"] + [None] * 11,
        [
            "Block",
            "Panchayat / Municipality / Corporation Zone",
            "Autumn",
            None,
            None,
            "Winter",
            None,
            None,
            "Summer",
            None,
            None,
            "Grand\nTotal",
        ],
        [None, None, "Wet", "Dry", "Total", "Wet", "Dry", "Total", "Wet", "Dry", "Total", None],
        ["THIRUVANANTHAPURAM"] + [None] * 11,
        ["1", "Athiyanoor", "0.00", "0", "0.00", "0.000", "0", "0.000", "0.00", "0", "0.00", "0.00"],
        ["2", "Kanjiramkulam", "0.00", "0", "0.00", "0.000", "0", "0.000", "0.00", "0", "0.00", "0.00"],
        ["5", "Venganoor", "0.00", "0", "0.00", "0.000", "0", "0.000", "0.15", "0.02", "0.17", "0.17"],
        ["Athiyannoor Total", None, "0", "0", "0.00", "0.000", "0", "0.000", "0.15", "0.02", "0.17", "0.17"],
    ]


def _lines_split_paddy_rows():
    """Same table as ``lines`` sees it: alternating stubs and shifted leaves."""
    return [
        ["TABLE - 3.1", None, None, None, None, None, None, None, None, None, None, None, None, None, None],
        [None, "PANCHAYATH WISE PADDY AREA 2023-24 UNIT:- Ha", None, None, None, None, None, None, None, None, None, None, None, None, None],
        ["Block", None, None, "Panchayat / Municipality / Corporation Zone", None, "Autumn", None, None, None, "Winter", None, None, None, "Grand\nTotal", None],
        [None, None, None, None, None, None, "Wet", None, "Dry", None, "Wet", None, "Dry", None, None],
        ["THIRUVANANTHAPURAM", None, None, None, None, None, None, None, None, None, None, None, None, None, None],
        [None, "1", None, None, "Athiyanoor", "0.00", None, "0", None, "0.000", None, "0", None, "0.00", None],
        ["2", None, None, "Kanjiramkulam", None, "0.00", None, "0", None, "0.000", None, "0", None, "0.00", None],
        [None, "5", None, None, "Venganoor", "0.00", None, "0", None, "0.000", None, "0", None, "0.17", None],
        ["Athiyannoor Total", None, None, None, None, "0", None, "0", None, "0.000", None, "0", None, "0.17", None],
    ]


def _paths(df):
    meta = list(df.attrs.get("dhara_column_meta") or [])
    return [list(m.get("header_path") or []) for m in meta]


def test_strict_grid_keeps_groups_and_section_row():
    df = dataframe_from_extracted_rows(_strict_paddy_rows())
    assert df.shape[1] == 12
    paths = _paths(df)
    assert paths[0] == ["Block"]
    assert paths[1] == ["Panchayat / Municipality / Corporation Zone"]
    assert paths[2:5] == [["Autumn", "Wet"], ["Autumn", "Dry"], ["Autumn", "Total"]]
    assert paths[5:8] == [["Winter", "Wet"], ["Winter", "Dry"], ["Winter", "Total"]]
    assert paths[8:11] == [["Summer", "Wet"], ["Summer", "Dry"], ["Summer", "Total"]]
    assert paths[11] == ["Grand Total"]
    assert df.iloc[0, 0] == "THIRUVANANTHAPURAM"
    assert df.iloc[1, 0] == "1"
    assert df.iloc[1, 1] == "Athiyanoor"
    assert df.iloc[3, 1] == "Venganoor"
    assert df.iloc[3, 8] == "0.15"


def test_split_lines_grid_rebuilds_the_same_header():
    df = dataframe_from_extracted_rows(_lines_split_paddy_rows())
    paths = _paths(df)
    assert paths[0] == ["Block"]
    assert paths[1] == ["Panchayat / Municipality / Corporation Zone"]
    assert paths[2:4] == [["Autumn", "Wet"], ["Autumn", "Dry"]]
    assert paths[4:6] == [["Winter", "Wet"], ["Winter", "Dry"]]
    assert paths[-1] == ["Grand Total"]
    # Season leaves stay under the season. They are not flattened to
    # "Autumn Wet", and Total is not pulled out of the group when present.
    assert all(len(p) == 2 and p[0] in {"Autumn", "Winter"} for p in paths[2:-1])
    assert df.iloc[0, 0] == "THIRUVANANTHAPURAM"
    assert list(df.iloc[1, :2]) == ["1", "Athiyanoor"]
    assert list(df.iloc[2, :2]) == ["2", "Kanjiramkulam"]
    assert "1" not in str(df.iloc[1, 1])
    assert "Block" not in paths[1][0]


def test_phantom_wide_grid_does_not_replace_clean_strict():
    # Same shape the paddy page produced: 22×12 clean vs 16×17 phantom-wide.
    strict = pd.DataFrame([["1"] * 12 for _ in range(22)])
    phantom = pd.DataFrame([["x"] * 17 for _ in range(16)])
    strict_c = {"method": "pymupdf_lines_strict", "df": strict, "bbox": [10, 10, 400, 500]}
    lines_c = {"method": "pymupdf_lines", "df": phantom, "bbox": [10, 10, 400, 500]}
    assert not _is_substantially_richer(lines_c, strict_c)
    kept = dedupe_candidates_by_bbox([strict_c, lines_c])
    assert len(kept) == 1
    assert kept[0]["method"] == "pymupdf_lines_strict"


def test_full_measure_grid_still_replaces_stub_fragment():
    fragment = pd.DataFrame({"Block": ["1", "2", "3"] * 10, "Name": ["A", "B", "C"] * 10})
    full = pd.DataFrame({f"C{i}": list(range(30)) for i in range(14)})
    frag_c = {"method": "pymupdf_lines_strict", "df": fragment, "bbox": [10, 20, 200, 400]}
    full_c = {"method": "pymupdf_lines", "df": full, "bbox": [10, 20, 400, 400]}
    assert _is_substantially_richer(full_c, frag_c)
    kept = dedupe_candidates_by_bbox([frag_c, full_c])
    assert len(kept) == 1
    assert kept[0]["method"] == "pymupdf_lines"


def test_sparse_wide_lines_does_not_replace_dense_strict():
    """Land-utilisation shape: clean 18-col strict vs bisected 29-col lines."""
    strict = pd.DataFrame(
        [[str(c) for c in range(1, 19)]]
        + [[str(i)] + [f"D{i}"] + [f"{1000 + j}.22" for j in range(16)] for i in range(1, 15)],
        columns=[f"H{c}" for c in range(18)],
    )
    # Wider grid with ~35% empty cells (phantom splits).
    wide_rows = []
    for r in range(16):
        row = []
        for c in range(29):
            row.append(f"v{r}_{c}" if c % 3 != 1 else None)
        wide_rows.append(row)
    wide = pd.DataFrame(wide_rows, columns=[f"W{c}" for c in range(29)])
    strict_c = {"method": "pymupdf_lines_strict", "df": strict, "bbox": [10, 10, 400, 500]}
    lines_c = {"method": "pymupdf_lines", "df": wide, "bbox": [10, 10, 400, 500]}
    assert not _is_substantially_richer(lines_c, strict_c)
    kept = dedupe_candidates_by_bbox([strict_c, lines_c])
    assert len(kept) == 1
    assert kept[0]["method"] == "pymupdf_lines_strict"
