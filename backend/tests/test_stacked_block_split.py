"""Additive stacked-schema split (marriage-registration style pages)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.grid_repair import (
    split_extracted_rows_on_table_markers,
)
from app.services.extraction.pdf.utils.stacked_block_split import (
    looks_like_stacked_schema_blocks,
    split_stacked_schema_blocks,
)
from app.services.extraction.pdf.utils import workers as w


def _marriage_stack() -> list[list]:
    header = [
        "S.No.",
        "Marriage Act",
        "Total No. of application Received",
        "No. of Registration Done",
    ]
    acts = [
        ["1", "Anand Marriage Act", "10", "8"],
        ["2", "Delhi Order 2014", "5", "4"],
        ["3", "Hindu Marriage Act", "20", "18"],
        ["4", "Special Marriage Act", "7", "6"],
    ]
    total = ["", "Total", "42", "36"]
    rows: list[list] = []
    for district in ("West", "Central", "Central North"):
        if rows:
            rows.append(["From 01.10.2026 TO 31.10.2026", None, None, None])
            rows.append([district, None, None, None])
            rows.append(list(header))
        else:
            rows.append(list(header))
        rows.extend([list(r) for r in acts])
        rows.append(list(total))
    return rows


def test_marriage_style_stack_splits_into_district_blocks():
    rows = _marriage_stack()
    assert looks_like_stacked_schema_blocks(rows)
    segs = split_stacked_schema_blocks(rows)
    assert len(segs) == 3
    # Later blocks keep date + district banners before their header.
    second = segs[1][0]
    assert any("01.10.2026" in str(c or "") for r in second for c in r)
    assert any(str(c or "").strip() == "Central" for r in second for c in r)
    for chunk, start, end in segs:
        assert end > start
        assert len(chunk) >= 5
        assert any(
            str(c or "").strip().lower() == "total" for r in chunk for c in r
        )


def test_single_table_with_total_does_not_split():
    rows = [
        ["S.No.", "Marriage Act", "Received", "Done"],
        ["1", "Hindu Marriage Act", "20", "18"],
        ["2", "Special Marriage Act", "7", "6"],
        ["", "Total", "27", "24"],
    ]
    assert not looks_like_stacked_schema_blocks(rows)
    segs = split_stacked_schema_blocks(rows)
    assert len(segs) == 1


def test_header_containing_total_word_is_not_treated_as_total_row():
    """Gate still works when a column title includes the word Total."""
    rows = _marriage_stack()
    assert looks_like_stacked_schema_blocks(rows)


def test_table_marker_path_produces_multiple_segments():
    rows = [
        ["S.No.", "Name", "Total"],
        ["1", "A", "1"],
        ["TABLE: B-10", None, None],
        ["S.No.", "Name", "Total"],
        ["1", "B", "2"],
    ]
    marker_segs = split_extracted_rows_on_table_markers(rows)
    assert len(marker_segs) == 2


def test_workers_hook_applies_stacked_split_only_for_single_marker_segment():
    rows = _marriage_stack()
    tab = MagicMock()
    tab.extract.return_value = rows
    tab.bbox = (0, 0, 100, 400)
    tab.rows = []

    def _df(seg_rows):
        # Minimal non-empty frame so candidate survives empty checks.
        return pd.DataFrame({"a": [1], "b": [2], "c": [3]})

    with patch(
        "app.services.extraction.pdf.utils.grid_repair.extract_needs_cell_clip",
        return_value=False,
    ), patch(
        "app.services.extraction.pdf.utils.header_utils.split_extracted_rows_on_table_markers",
        side_effect=lambda r: [([list(x) for x in r], 0, len(r))],
    ), patch(
        "app.services.extraction.pdf.utils.header_utils.dataframe_from_extracted_rows",
        side_effect=_df,
    ), patch(
        "app.services.extraction.pdf.confidence_validation.table_confidence.looks_like_chart_candidate",
        return_value=(False, ""),
    ), patch(
        "app.services.extraction.pdf.confidence_validation.table_confidence.looks_like_bullet_list_candidate",
        return_value=(False, ""),
    ), patch(
        "app.services.extraction.pdf.confidence_validation.table_confidence.looks_like_toc_or_index_candidate",
        return_value=(False, ""),
    ):
        cands = w._candidates_from_pymupdf_table(
            tab, page_num=1, method="pymupdf_lines"
        )

    assert len(cands) == 3
    assert all(c.get("split_from_merged_grid") for c in cands)


def test_workers_hook_skips_stacked_when_marker_already_split():
    tab = MagicMock()
    tab.extract.return_value = [["a"]]
    tab.bbox = (0, 0, 10, 10)
    tab.rows = []

    marker_segs = [
        ([["S.No.", "Name"], ["1", "A"]], 0, 2),
        ([["TABLE: B-10"], ["S.No.", "Name"], ["1", "B"]], 2, 5),
    ]

    with patch(
        "app.services.extraction.pdf.utils.grid_repair.extract_needs_cell_clip",
        return_value=False,
    ), patch(
        "app.services.extraction.pdf.utils.header_utils.split_extracted_rows_on_table_markers",
        return_value=marker_segs,
    ), patch(
        "app.services.extraction.pdf.utils.header_utils.dataframe_from_extracted_rows",
        side_effect=lambda seg: pd.DataFrame({"a": [1], "b": [2], "c": [3]}),
    ), patch(
        "app.services.extraction.pdf.confidence_validation.table_confidence.looks_like_chart_candidate",
        return_value=(False, ""),
    ), patch(
        "app.services.extraction.pdf.confidence_validation.table_confidence.looks_like_bullet_list_candidate",
        return_value=(False, ""),
    ), patch(
        "app.services.extraction.pdf.confidence_validation.table_confidence.looks_like_toc_or_index_candidate",
        return_value=(False, ""),
    ), patch(
        "app.services.extraction.pdf.utils.stacked_block_split.looks_like_stacked_schema_blocks",
    ) as gate:
        cands = w._candidates_from_pymupdf_table(
            tab, page_num=1, method="pymupdf_lines"
        )
        gate.assert_not_called()

    assert len(cands) == 2
