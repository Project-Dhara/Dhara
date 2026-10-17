"""Mid-grid TABLE-marker splits must not cut cause-of-death E48/E58 rows."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.caption import (
    _is_mid_grid_table_split_id,
    _is_table_id_only,
)
from app.services.extraction.pdf.utils.grid_repair import (
    _row_is_new_table_marker,
    split_extracted_rows_on_table_markers,
)


def test_bare_disease_serial_is_not_mid_grid_split_id():
    assert _is_table_id_only("E48")  # still a short code for caption helpers
    assert not _is_mid_grid_table_split_id("E48")
    assert not _is_mid_grid_table_split_id("E58")
    assert _is_mid_grid_table_split_id("D-14")
    assert _is_mid_grid_table_split_id("TABLE: B-6")


def test_disease_sex_pair_row_is_not_table_marker():
    row = [
        "E48",
        "Transport Accidents (V01-V99)",
        "M",
        "10",
        "0",
        "2",
        "0",
        "0",
        "1",
        "0",
        "0",
        "0",
        "0",
        "0",
        "13",
    ]
    assert not _row_is_new_table_marker(row)


def test_real_second_table_banner_still_splits():
    rows = [
        ["S.No.", "Name", "Sex", "<1", "Total"],
        ["(1)", "(2)", "(3)", "(4)", "(5)"],
        ["1", "Plague (A20)", "M", "0", "0"],
        ["", "", "F", "0", "0"],
        ["TABLE: B-10", None, None, None, None],
        ["S.No.", "Name", "Sex", "<1", "Total"],
        ["1", "Other", "M", "1", "1"],
    ]
    segs = split_extracted_rows_on_table_markers(rows)
    assert len(segs) == 2
    assert segs[0][0][0][0] == "S.No."
    assert any(
        str(c or "").startswith("TABLE")
        for r in segs[1][0]
        for c in r
    )


def test_cause_of_death_e_codes_stay_one_segment():
    rows = [
        ["S.No.", "Name of the Disease", "Sex", "<1", "1-4", "Total"],
        ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)"],
        ["E48", "Transport Accidents (V01-V99)", "M", "0", "0", "0"],
        ["", "", "F", "0", "0", "0"],
        ["E49", "Accidental Falls (W00-W19)", "M", "1", "0", "1"],
        ["", "", "F", "0", "0", "0"],
        ["E58", "Late effects of external causes (Y85-Y89)", "M", "0", "0", "0"],
        ["", "", "F", "0", "0", "0"],
        ["", "Total", "M", "10", "2", "12"],
        ["", "", "F", "8", "1", "9"],
        ["", "", "T", "18", "3", "21"],
    ]
    segs = split_extracted_rows_on_table_markers(rows)
    assert len(segs) == 1
    assert len(segs[0][0]) == len(rows)
