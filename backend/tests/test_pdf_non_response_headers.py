"""Non-response annexures keep Planned/Analysed/reason leaves under groups.

Vertical header text and wrap rows (``Experiments not`` / ``conducted due to``)
must not flatten into a single L1 band or leak into the body.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.grid_repair import (
    extract_needs_cell_clip,
    fold_header_label_wrap_rows,
)
from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows


def _non_response_rows():
    """Cell-accurate 13-col grid (as ``get_textbox`` per cell would yield)."""
    empty = [None] * 12
    return [
        ["ANNEXURE-24"] + empty,
        ["DETAILS OF NON RESPONSE 2023-24"] + empty,
        [
            "Name of Crop: Paddy",
            None,
            None,
            None,
            "Season - Summer (Rabi II)",
            None,
            None,
            None,
            None,
            None,
            "Appendix: D6",
            None,
            None,
        ],
        [
            "Sl No",
            "Name of District",
            "No of experiments",
            None,
            "Experiments not",
            None,
            "Sub Total (5+6)",
            "Experiments rejected due to",
            None,
            None,
            None,
            "Sub Total (8+9+10+11)",
            "Total",
        ],
        [None, None, None, None, "conducted due to", None, None, None, None, None, None, None, None],
        [
            None,
            None,
            "Planned",
            "Analysed",
            "Prior harvest of the cultivator",
            "Other Reasons",
            None,
            "Non Availablity of crop",
            "Unrelailable doubtful data",
            "Late receipt of returns",
            "Discrepancy of data",
            None,
            None,
        ],
        [str(i) for i in range(1, 14)],
        ["1", "Thiruvananthapuram", "90", "90", None, None, None, None, None, None, None, None, None],
        ["2", "Kollam", "58", "58", None, None, None, None, None, None, None, None, None],
        ["KERALA STATE", None, "1596", "1596", None, None, None, None, None, None, None, None, None],
    ]


def _paths(df):
    meta = list(df.attrs.get("dhara_column_meta") or [])
    return [list(m.get("header_path") or []) for m in meta]


def test_cell_clip_gate_ignores_captions_but_catches_glue():
    caption = [["DISTRICTWISE AREA PRODUCTIVITY AND PRODUCTION OF RICE FOR LOCAL"] + [None] * 5]
    assert not extract_needs_cell_clip(caption)
    glued_leaves = [[
        "Sl No",
        "District",
        "Planned",
        "Analysed Prior harvest of the cultivator Other Reasons",
        "Total",
    ]]
    assert extract_needs_cell_clip(glued_leaves)
    glued_index = [["1", "2", "3 4 5 6", "7", "8", "9", "10", "11", "12", "13"]]
    assert extract_needs_cell_clip(glued_index)
    # One value per line is a row stack, not columns smashed together.
    stacked = [[
        "Months",
        "167\n268\n306",
        "79\n105\n132",
        "246\n373\n438",
    ]]
    assert not extract_needs_cell_clip(stacked)


def test_fold_merges_conducted_due_to_wrap():
    folded = fold_header_label_wrap_rows(_non_response_rows())
    # Wrap row removed; parent cell completed.
    assert any(
        "Experiments not conducted due to" in (_cell or "")
        for row in folded
        for _cell in row
        if _cell
    )
    assert not any(
        str(c) == "conducted due to"
        for row in folded
        for c in row
        if c
    )


def test_non_response_multilevel_headers():
    df = dataframe_from_extracted_rows(_non_response_rows())
    assert df.shape[1] == 13
    paths = _paths(df)
    assert paths[0] == ["Sl No"]
    assert paths[1] == ["Name of District"]
    assert paths[2] == ["No of experiments", "Planned"]
    assert paths[3] == ["No of experiments", "Analysed"]
    assert paths[4] == ["Experiments not conducted due to", "Prior harvest of the cultivator"]
    assert paths[5] == ["Experiments not conducted due to", "Other Reasons"]
    assert paths[6] == ["Sub Total (5+6)"]
    assert paths[7] == ["Experiments rejected due to", "Non Availablity of crop"]
    assert paths[8] == ["Experiments rejected due to", "Unrelailable doubtful data"]
    assert paths[9] == ["Experiments rejected due to", "Late receipt of returns"]
    assert paths[10] == ["Experiments rejected due to", "Discrepancy of data"]
    assert paths[11] == ["Sub Total (8+9+10+11)"]
    assert paths[12] == ["Total"]
    # Leaf labels must not appear as body values.
    body_flat = " ".join(str(v) for v in df.values.ravel() if v is not None and str(v) != "nan")
    assert "Planned" not in body_flat
    assert "conducted due to" not in body_flat
    assert "Thiruvananthapuram" in [str(v) for v in df.iloc[:, 1].tolist()]
