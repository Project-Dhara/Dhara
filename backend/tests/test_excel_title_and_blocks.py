"""Excel title cleanup + unmarked-sheet block detection."""
from __future__ import annotations

from app.services.ingestion.wizard.extractor import TableExtractor
from app.services.metadata.validation import normalize_table_title
from app.services.extraction.pdf.utils.header_utils import extract_in_grid_caption


def test_normalize_drops_column_list_suffix():
    title = "Scheme Summary (Basic Statistics) — Scheme name, beneficiaries, budget"
    cols = [
        "Scheme name",
        "beneficiaries",
        "budget",
        "Allocated amount",
        "Utilised amount",
        "Status",
        "Year",
        "Remarks",
    ]
    assert normalize_table_title(title, cols) == "Scheme Summary (Basic Statistics)"


def test_normalize_keeps_short_geo_subtitle():
    assert normalize_table_title("Live births — URBAN", None) == "Live births — URBAN"


def test_normalize_keeps_long_vital_statistics_title():
    # Hard 90-char truncation used to cut mid-phrase after "FOR".
    title = (
        "PREGNANCY RELATED DEATHS BY AGE GROUP OF THE DECEASED (MOTHER) "
        "AND CAUSE OF DEATH FOR MEDICALLY CERTIFIED OR NOT DEATHS (URBAN)"
    )
    assert normalize_table_title(title, None) == title


def test_caption_joins_wrapped_title_continuation():
    # Title split across two full-width banner rows (common Excel wrap).
    full = (
        "PREGNANCY RELATED DEATHS BY AGE GROUP OF THE DECEASED (MOTHER) "
        "AND CAUSE OF DEATH FOR MEDICALLY CERTIFIED OR NOT DEATHS (URBAN)"
    )
    part1 = "PREGNANCY RELATED DEATHS BY AGE GROUP OF THE DECEASED (MOTHER) AND CAUSE OF DEATH FOR"
    part2 = "MEDICALLY CERTIFIED OR NOT DEATHS (URBAN)"
    rows = [
        ["TABLE: D-18"] + [None] * 7,
        [part1] + [None] * 7,
        [part2] + [None] * 7,
        ["SL. NO.", "CAUSE"] + [f"C{i}" for i in range(6)],
    ]
    # Make banners look full-width (same label repeated).
    rows[0] = ["TABLE: D-18"] * 8
    rows[1] = [part1] * 8
    rows[2] = [part2] * 8
    cap = extract_in_grid_caption(rows)
    assert cap["title"] == full
    assert cap["rows_consumed"] == 3


def test_caption_does_not_consume_column_list_banner():
    rows = [
        ["Scheme Summary (Basic Statistics)"] + [None] * 7,
        ["Scheme name, beneficiaries, budget"] + [None] * 7,
        ["A", "B", "C", "D", "E", "F", "G", "H"],
        [1, 2, 3, 4, 5, 6, 7, 8],
    ]
    # Make row 0/1 look like full-width banners (same label repeated).
    rows[0] = ["Scheme Summary (Basic Statistics)"] * 8
    rows[1] = ["Scheme name, beneficiaries, budget"] * 8
    cap = extract_in_grid_caption(rows)
    assert cap["title"] == "Scheme Summary (Basic Statistics)"
    assert cap["rows_consumed"] == 1


def test_unmarked_sheet_is_single_block():
    # Decorative blank gap mid-sheet must not split into two tables.
    grid = (
        [["Scheme Summary (Basic Statistics)"] + [None] * 3]
        + [["Name", "Beneficiaries", "Budget", "Year"]]
        + [[f"S{i}", i * 10, i * 100, 2020 + i] for i in range(5)]
        + [[None, None, None, None], [None, None, None, None]]
        + [[f"T{i}", i, i, 2010 + i] for i in range(4)]
    )
    blocks = TableExtractor(skip_llm=True)._find_blocks(grid)
    assert len(blocks) == 1
    assert blocks[0] == (0, len(grid) - 1)
