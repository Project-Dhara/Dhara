"""Rotated / stacked PDF column-header repair."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.extraction.pdf.utils.caption import _row_is_column_number_strip
from app.services.extraction.pdf.utils.header_utils import dataframe_from_extracted_rows
from app.services.extraction.pdf.utils.vertical_headers import (
    collapse_stacked_header_cell,
    header_band_row_count,
    is_plausible_header_label,
    looks_like_stacked_letter_cell,
    normalize_multiline_header_cell,
    repair_vertical_header_rows,
    score_header_label,
)

# Checked-in fixture (copied from the Kerala Agricultural Statistics sample).
SAMPLE_PDF = Path(__file__).resolve().parent / "fixtures" / "area_under_crops_vertical_headers.pdf"
_ALT_SAMPLE = Path(
    "/home/ubuntu/.cursor/projects/home-ubuntu-data-dhara-Dhara/attachments/"
    "9cbe660b-86d4-4111-b36a-f3743e40d331/1822_59-66_1.pdf"
)
if not SAMPLE_PDF.is_file() and _ALT_SAMPLE.is_file():
    SAMPLE_PDF = _ALT_SAMPLE


def _stack(*letters: str) -> str:
    """Join single letters with newlines (avoids \\t escape pitfalls)."""
    return "\n".join(letters)


def test_looks_like_stacked_letter_cell():
    assert looks_like_stacked_letter_cell(_stack("A", "u", "t", "u", "m", "n"))
    assert looks_like_stacked_letter_cell("A u t u m n")
    assert not looks_like_stacked_letter_cell("Autumn")
    assert not looks_like_stacked_letter_cell("Wet Paddy")


def test_collapse_prefers_natural_word_over_reverse():
    assert collapse_stacked_header_cell(_stack("A", "u", "t", "u", "m", "n")) == "Autumn"
    # Reversed letter order (common when reading direction is wrong).
    assert collapse_stacked_header_cell(_stack("n", "m", "u", "t", "u", "A")) == "Autumn"
    assert collapse_stacked_header_cell(_stack("M", "a", "i", "z", "e")) == "Maize"


def test_normalize_newline_broken_words():
    assert normalize_multiline_header_cell("Grand\ntotal") == "Grand total"
    assert normalize_multiline_header_cell("Total\nFood\nGrains") == "Total Food Grains"
    assert normalize_multiline_header_cell("Total\nPulses") == "Total Pulses"
    assert normalize_multiline_header_cell("Sl.\nN\no.") == "Sl. No."
    assert normalize_multiline_header_cell("Sl. N o.") == "Sl. No."


def test_score_rejects_colspan_bleed_garbage():
    garbage = "m21111694857441626Autumn0837571229978373788013002072..............26371074440645"
    assert not is_plausible_header_label(garbage)
    assert score_header_label("Paddy") > score_header_label(garbage)
    assert score_header_label("Autumn") > score_header_label("A u t u m n")
    assert score_header_label("Wet Paddy") > score_header_label("yddap teW")


def test_column_number_strip_accepts_offset_sequence():
    row = ["3", "4", "5", "6", "7", "8", "9", "10", "11"]
    assert _row_is_column_number_strip(row, len(row))
    assert not _row_is_column_number_strip(["1", "3", "5", "7"], 4)


def test_repair_collapses_stacked_header_band():
    rows = [
        ["Sl. No.", "District", "Wet Paddy", "", "", "", "Dry Paddy", "", "", ""],
        [
            "",
            "",
            _stack("A", "u", "t", "u", "m", "n"),
            _stack("W", "i", "n", "t", "e", "r"),
            _stack("S", "u", "m", "m", "e", "r"),
            _stack("T", "o", "t", "a", "l"),
            _stack("A", "u", "t", "u", "m", "n"),
            _stack("W", "i", "n", "t", "e", "r"),
            _stack("S", "u", "m", "m", "e", "r"),
            _stack("T", "o", "t", "a", "l"),
        ],
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
        ["1", "Thiruvananthapuram", "10.0", "20.0", "30.0", "60.0", "1.0", "2.0", "3.0", "6.0"],
    ]
    repaired, meta = repair_vertical_header_rows(rows)
    assert meta["repaired"] is True
    assert meta["repaired_cells"] >= 4
    leaf = repaired[1]
    assert leaf[2] == "Autumn"
    assert leaf[3] == "Winter"
    assert leaf[5] == "Total"


def test_repair_does_not_corrupt_good_paddy_parent():
    """Wide colspan parents must not be replaced by page-bleed garbage."""
    rows = [
        ["TABLE-3", "", "", "", "", ""],
        ["AREA UNDER CROPS", "", "", "", "", ""],
        ["Sl.\nN\no.", "District", "Paddy", "", "", ""],
        ["", "", "Wet Paddy", "", "", ""],
        ["", "", "Autumn", "Winter", "Summer", "Total"],
        ["1", "2", "3", "4", "5", "6"],
        ["1", "Kollam", "1.1", "2.2", "3.3", "6.6"],
    ]
    repaired, meta = repair_vertical_header_rows(rows)
    assert repaired[2][2] == "Paddy"
    assert repaired[2][0] == "Sl. No."
    assert meta["repaired"] is True


def test_dataframe_builds_multilevel_paths_after_repair():
    rows = [
        ["Sl. No.", "District", "Wet Paddy", "", "", ""],
        ["", "", "Autumn", "Winter", "Summer", "Total"],
        ["1", "2", "3", "4", "5", "6"],
        ["1", "Kollam", "1.1", "2.2", "3.3", "6.6"],
    ]
    repaired, _ = repair_vertical_header_rows(rows)
    df = dataframe_from_extracted_rows(repaired)
    meta = df.attrs.get("dhara_column_meta") or []
    assert len(meta) >= 6
    # Leaf under Wet Paddy should carry a multi-level path.
    autumn_meta = next(
        (m for m in meta if "Autumn" in str(m.get("name") or "")
         or "Autumn" in " / ".join(m.get("header_path") or [])),
        None,
    )
    assert autumn_meta is not None
    path = autumn_meta.get("header_path") or []
    assert any("Wet" in str(p) or "Paddy" in str(p) for p in path) or "Autumn" in path


def test_header_band_stops_before_data():
    rows = [
        ["A", "B", "C"],
        ["1", "2", "3"],
        ["x", "10.5", "20.5"],
    ]
    assert header_band_row_count(rows) == 2


def test_headers_still_look_stacked():
    from app.services.extraction.pdf.utils.vertical_headers import headers_still_look_stacked

    assert headers_still_look_stacked(["District", _stack("A", "u", "t", "u", "m", "n")])
    assert headers_still_look_stacked(["Wet Paddy / A u t u m n"])
    assert headers_still_look_stacked(["Sl. N o."])
    assert not headers_still_look_stacked(["Wet Paddy / Autumn", "Maize", "Sl. No."])


def test_structural_bucket_routes_stacked_headers_to_header_llm():
    import pandas as pd

    from app.services.extraction.pdf.confidence_validation.table_confidence import (
        _structural_bucket_for_df,
    )

    df = pd.DataFrame(
        [
            ["1", "10.0", "20.0"],
            ["2", "11.0", "21.0"],
            ["3", "12.0", "22.0"],
        ],
        columns=["District", _stack("A", "u", "t", "u", "m", "n"), "Winter"],
    )
    bucket, reason, _ = _structural_bucket_for_df(df)
    assert bucket == "llm"
    assert "rotated or stacked" in reason


def test_synthetic_pdf_stacked_upright_letters_repaired():
    """Tall cells with one upright glyph per line (common CRS failure mode)."""
    import pymupdf

    from app.services.extraction.pdf.utils.vertical_headers import (
        rebuild_cell_text_from_page,
        repair_vertical_header_rows,
    )

    doc = pymupdf.open()
    page = doc.new_page(width=420, height=360)
    # One tall header cell + stub + data.
    xs = [40, 140, 220]
    ys = [40, 200, 260]
    shape = page.new_shape()
    for x in xs:
        shape.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        shape.draw_line((xs[0], y), (xs[-1], y))
    shape.finish(color=(0, 0, 0), width=0.8)
    shape.commit()

    page.insert_text((55, 110), "District", fontsize=9)
    # Stack upright letters bottom→top inside the measure header cell.
    label = "Autumn"
    x = 165
    # Draw from bottom of header band upward (how many stats PDFs place glyphs).
    y = 185
    for ch in label:
        page.insert_text((x, y), ch, fontsize=8)
        y -= 12
    page.insert_text((55, 235), "Kollam", fontsize=9)
    page.insert_text((160, 235), "10.0", fontsize=9)

    found = page.find_tables(strategy="lines_strict")
    assert found.tables, "expected a ruled table in the synthetic PDF"
    tab = found.tables[0]
    raw = tab.extract()
    repaired, meta = repair_vertical_header_rows(raw, page=page, tab=tab)
    # Page-level rebuild of the header cell should read Autumn (either order).
    clip = (xs[1], ys[0], xs[2], ys[1])
    rebuilt = rebuild_cell_text_from_page(page, clip)
    doc.close()
    assert "Autumn" in {rebuilt, *(c for row in repaired for c in row if c)}
    # If extract already joined letters with newlines, repair must collapse them.
    if any(looks_like_stacked_letter_cell(c) for row in raw for c in row):
        assert meta["repaired"] is True


def test_real_crops_pdf_vertical_headers():
    """Regression: AREA UNDER CROPS page from Kerala Agricultural Statistics PDF."""
    import pymupdf
    import pytest

    if not SAMPLE_PDF.is_file():
        pytest.skip(f"sample PDF not present: {SAMPLE_PDF}")

    from app.services.extraction.pdf.utils.vertical_headers import (
        headers_still_look_stacked,
        repair_vertical_header_rows,
    )

    doc = pymupdf.open(SAMPLE_PDF)
    page = doc[0]
    found = page.find_tables(strategy="lines_strict")
    assert found.tables
    tab = found.tables[0]
    raw = tab.extract()
    repaired, meta = repair_vertical_header_rows(raw, page=page, tab=tab)
    doc.close()

    # Must not corrupt the Paddy group banner.
    assert repaired[2][2] == "Paddy"
    assert repaired[2][0] == "Sl. No."
    assert repaired[3][2] == "Wet Paddy"
    assert repaired[3][6] == "Dry Paddy"
    assert repaired[4][2] == "Autumn"
    assert repaired[4][3] == "Winter"
    assert "Grand" in str(repaired[3][10])
    assert meta["repaired"] is True

    df = dataframe_from_extracted_rows(repaired)
    names = [str(c) for c in df.columns]
    assert names[0] == "Sl. No."
    assert "Autumn" in names[2]
    assert not headers_still_look_stacked(names)

    meta_cols = df.attrs.get("dhara_column_meta") or []
    autumn = next(
        (m for m in meta_cols if (m.get("header_path") or [])[-1:] == ["Autumn"]),
        None,
    )
    assert autumn is not None
    path = autumn.get("header_path") or []
    assert "Wet Paddy" in path or "Paddy" in path
