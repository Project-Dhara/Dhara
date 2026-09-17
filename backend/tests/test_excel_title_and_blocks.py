"""Excel title cleanup + unmarked-sheet block detection."""
from __future__ import annotations

from extraction.extractor import TableExtractor
from metadata.validation import normalize_table_title
from pdf.pdf_header_utils import extract_in_grid_caption


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
