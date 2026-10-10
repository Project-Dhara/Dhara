"""In-cell count+(pct) stacks must stay on one row, not expand into orphans."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.header_utils import (
    _is_parenthetical_share_token,
    _measure_parts_for_row_expand,
    dataframe_from_extracted_rows,
    fold_orphan_parenthetical_share_rows,
)


def _cell(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in {"", "none", "nan"} else s


LOCAL_BODY_GRID = [
    ["Sl.No.", "Name of Local Body", "No. of Births", None, None],
    [None, None, "Rural", "Urban", "Combined"],
    ["A", "Total MCD (i+ ii + iii)", "22711", "303128", "325839\n(88.06)"],
    ["(i)", "North DMC", "14094", "114501", "128595\n(34.76)"],
    ["(ii)", "South DMC", "5051", "115863", "120914\n(32.67)"],
    ["(iii)", "East DMC", "3566", "72764", "76330\n(20.63)"],
    ["B", "NDMC", "197", "40837", "41034\n(11.09)"],
    ["C", "DCB", "1997", "1130", "3127\n(0.85)"],
    ["", "ALL (A+B+C)", "24905\n(6.73)", "345095\n(93.27)", "370000\n(100.00)"],
]


def test_parenthetical_share_token():
    assert _is_parenthetical_share_token("(88.06)")
    assert _is_parenthetical_share_token("*(45.18)")
    assert _is_parenthetical_share_token("(100.00)")
    assert not _is_parenthetical_share_token("325839")
    assert not _is_parenthetical_share_token("MCD")


def test_measure_parts_collapse_count_share_stack():
    parts = _measure_parts_for_row_expand("325839\n(88.06)")
    assert parts == ["325839\n(88.06)"]
    # Real stacked measures (M/F ages) must still expand.
    ages = _measure_parts_for_row_expand("59\n35\n0\n1")
    assert ages == ["59", "35", "0", "1"]


def test_local_body_keeps_share_in_same_row():
    df = dataframe_from_extracted_rows(LOCAL_BODY_GRID)
    assert df.shape[0] == 7, (df.shape, df.values.tolist())
    assert df.shape[1] == 5
    combined = [_cell(v) for v in df["Combined"].tolist()]
    assert combined[0] == "325839 (88.06)"
    assert combined[1] == "128595 (34.76)"
    assert combined[-1] == "370000 (100.00)"
    rural = [_cell(v) for v in df["Rural"].tolist()]
    assert rural[-1] == "24905 (6.73)"
    # No orphan share-only rows.
    assert not any(v.startswith("(") and v.endswith(")") and " " not in v for v in combined)


def test_sparse_orphan_share_row_folds_into_parent():
    """Already-split ``— | (88.06)`` rows (post-expand legacy) fold back."""
    import pandas as pd

    df = pd.DataFrame(
        [
            ["A", "Total MCD", "22711", "303128", "325839"],
            ["—", "—", "—", "—", "(88.06)"],
            ["B", "NDMC", "197", "40837", "41034"],
            ["—", "—", "—", "—", "(11.09)"],
        ],
        columns=["Sl.No.", "Name", "Rural", "Urban", "Combined"],
    )
    out = fold_orphan_parenthetical_share_rows(df)
    assert out.shape[0] == 2
    assert _cell(out.iloc[0]["Combined"]) == "325839 (88.06)"
    assert _cell(out.iloc[1]["Combined"]) == "41034 (11.09)"


def test_dense_blank_stub_share_rows_still_kept():
    """Year×education full share rows must remain separate (existing behaviour)."""
    grid = [
        ["Year", "A", "B", "C", "D"],
        ["1991", "28815", "37043", "41435", "164727"],
        ["", "(10.6)", "(13.6)", "(15.2)", "(60.6)"],
        ["2000", "57542", "52426", "82579", "124829"],
        ["", "(18.1)", "(16.6)", "(26.0)", "(39.3)"],
    ]
    df = dataframe_from_extracted_rows(grid)
    assert df.shape[0] == 4
    years = [_cell(v) for v in df.iloc[:, 0].tolist()]
    assert years == ["1991", "", "2000", ""]
    assert _cell(df.iloc[1, 1]) == "(10.6)"
