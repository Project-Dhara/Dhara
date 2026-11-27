"""Regression: chap10 transport side-by-side sheets stay as two full panels."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.ingestion.layout_table_extractor import (
    Config,
    extract_file,
    load_excel_grids,
    segment_sheet,
)

FIXTURE = Path(__file__).parent / "fixtures" / "chap10_transport.xlsx"


def _df_text(df) -> str:
    return " ".join(str(v) for v in df.astype(str).values.ravel() if v and v != "None")


def test_chap10_sheet_10_2c_is_two_side_by_side_panels():
    assert FIXTURE.is_file(), f"missing fixture {FIXTURE}"
    cfg = Config()
    grids = {name: g for name, g, _ in load_excel_grids(FIXTURE, cfg)}
    sheet = next(n for n in grids if "2(c)" in n.replace(" ", ""))
    blocks = segment_sheet(grids[sheet], cfg)
    assert len(blocks) == 2, [(b.r0, b.r1, b.c0, b.c1) for b in blocks]
    left, right = blocks[0], blocks[1]
    assert left.c0 < right.c0
    assert left.c1 < right.c0  # gutter between panels
    # Full-height panels, not row scraps
    assert left.r1 - left.r0 >= 20
    assert right.r1 - right.r0 >= 20

    tables = [t for t in extract_file(FIXTURE, cfg) if "2(c)" in t.sheet.replace(" ", "")]
    assert len(tables) == 2
    # Left panel then right (A… before G…)
    assert tables[0].cell_range.startswith("A")
    assert tables[1].cell_range.startswith("G")
    assert tables[0].df.shape[0] >= 10
    assert tables[1].df.shape[0] >= 6

    right_t = tables[1]
    data_cols = [c for c in right_t.df.columns if not str(c).startswith("_")]
    # Post-index serial row with non-numeric measure must stay data, not header path
    assert data_cols == ["S.No.", "Other activities of DMRC", "Numbers"], data_cols
    assert all("63.07" not in str(c) and "Lakhs" not in str(c) for c in data_cols)
    kinds = list(right_t.df["_row_kind"])
    assert "index" in kinds
    assert kinds[0] == "index", kinds[:5]
    assert "63.07 Lakhs" in _df_text(right_t.df)
    assert right_t.title and "Activities of Delhi Metro" in right_t.title


def test_chap10_tables_carry_sheet_captions_as_titles():
    """Caption bands peel into ExtractedTable.title (no scrap title-only tables)."""
    assert FIXTURE.is_file()
    cfg = Config()
    tables = extract_file(FIXTURE, cfg)

    scrap_title_only = [
        t for t in tables
        if t.df.shape[0] <= 3
        and not (t.title or "").strip()
        and t.sheet.replace(" ", "") == "Table10.(2a)"
    ]
    assert not scrap_title_only

    titled = [t for t in tables if (t.title or "").strip()]
    assert len(titled) >= 6, [t.sheet for t in tables if not (t.title or "").strip()]
    assert any("Delhi Metro" in (t.title or "") for t in tables)
    assert any("DIMTS" in (t.title or "") or "Multi-Model" in (t.title or "") for t in tables)
    paren_2a = [t for t in tables if t.sheet.replace(" ", "") == "Table10.(2a)" and t.df.shape[0] >= 6]
    assert paren_2a
    assert all((t.title or "").strip() for t in paren_2a)

def test_chap10_sheet_10_2a_two_year_panels_with_full_rows():
    assert FIXTURE.is_file()
    cfg = Config()
    tables = [t for t in extract_file(FIXTURE, cfg) if t.sheet.replace(" ", "") == "Table10.2a"]
    assert len(tables) == 2
    assert tables[0].cell_range.startswith("A")
    assert tables[1].cell_range.startswith("J")
    # Activity list (not last-row-only)
    assert tables[0].df.shape[0] >= 6
    assert tables[1].df.shape[0] >= 6


def test_chap10_terminal_wrap_rows_appear_in_body():
    """Last bilingual wraps stay as section rows in Preview, not notes-only."""
    assert FIXTURE.is_file()
    cfg = Config()
    tables = extract_file(FIXTURE, cfg)

    right_2a = [
        t for t in tables
        if t.sheet.replace(" ", "") == "Table10.2a" and t.cell_range.startswith("J")
    ]
    assert right_2a
    blob = _df_text(right_2a[0].df)
    assert "10000 buses" in blob
    assert all("10000 buses" not in (n or "") for n in (right_2a[0].notes or []))

    left_2c = [
        t for t in tables
        if "2(c)" in t.sheet.replace(" ", "") and t.cell_range.startswith("A")
    ]
    assert left_2c
    blob_c = _df_text(left_2c[0].df)
    assert "Depot Station" in blob_c or "Aqua" in blob_c


def test_chap10_sheet_10_paren_2a_includes_ncr_through_depots():
    """Table10.(2a): Accidents…NCR…Workshop…Depots in side panels; no Depots-only scrap table."""
    assert FIXTURE.is_file()
    cfg = Config()
    grids = {name: g for name, g, _ in load_excel_grids(FIXTURE, cfg)}
    sheet = next(n for n in grids if n.replace(" ", "") == "Table10.(2a)")
    blocks = segment_sheet(grids[sheet], cfg)
    data_blocks = [b for b in blocks if b.an.data_start is not None and b.r1 - b.r0 >= 8]
    assert len(data_blocks) == 2, [(b.r0, b.r1, b.c0, b.c1) for b in blocks]
    assert data_blocks[0].c0 < data_blocks[1].c0
    # Both panels include trailing Depots rows
    assert all(b.r1 >= 21 for b in data_blocks)

    tables = [t for t in extract_file(FIXTURE, cfg) if t.sheet.replace(" ", "") == "Table10.(2a)"]
    panels = [t for t in tables if t.df.shape[0] >= 6]
    assert len(panels) == 2
    right = next(t for t in panels if "Description" in "".join(map(str, t.df.columns)) or t.cell_range.startswith("I"))
    blob = _df_text(right.df)
    assert "Accidents" in blob
    assert "NCR" in blob
    assert "Workshop" in blob or "Worksh" in blob
    assert "Depots" in blob
    # Footnotes stay notes, not a third data scrap
    assert any("Note" in (n or "") or "Source" in (n or "") for n in (right.notes or []))
    scrap = [
        t for t in tables
        if t.df.shape[0] <= 3 and "Depots" in _df_text(t.df) and "Accidents" not in _df_text(t.df)
    ]
    assert not scrap


def test_chap10_sheet_10_2b_keeps_workshop_depots_and_wraps():
    assert FIXTURE.is_file()
    cfg = Config()
    tables = [t for t in extract_file(FIXTURE, cfg) if t.sheet.replace(" ", "") == "Table10.2(b)"]
    assert len(tables) == 2
    left, right = tables[0], tables[1]
    assert left.cell_range.startswith("A")
    assert right.cell_range.startswith("G")

    left_blob = _df_text(left.df)
    assert "Break-down per 10000 buses" in left_blob or "10000 buses" in left_blob

    right_blob = _df_text(right.df)
    assert "Workshop" in right_blob or "वर्क" in right_blob
    assert "Depots" in right_blob or "डिपों" in right_blob
    # serial 10 / 11 present on right panel
    assert "10" in right_blob and "11" in right_blob
