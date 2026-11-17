#!/usr/bin/env python3
"""
table_extractor.py  --  layout-driven table extraction from Excel / CSV files.

No hard-coded sheet names, cell addresses or column names. Structure is inferred
from layout features only:

  * merged ranges, blank gaps, row "type profiles" (numeric vs text density)
  * formulas (SUM ranges mark total rows) and numeric reconciliation
  * repeating leaf-header patterns, fill-down of parent labels

Handles: several tables per sheet (stacked or side by side), title/caption rows,
multi-level (merged) headers, index rows like (1)(2)(3), section rows, mid-table
notes, repeated page headers, sub-totals / totals, hierarchical row labels via
vertical merges, formulas without cached values, phantom sheet sizes, CSV/TSV.

Quick use
---------
    from table_extractor import extract_file, extract_paths
    tables = extract_file("report.xlsx")
    for t in tables:
        print(t.summary())
        df   = t.data_only()          # clean wide frame, totals removed
        long = t.to_long()            # tidy long format with column-path levels + source cells

CLI
---
    python table_extractor.py data/ -o out/ --long
    python table_extractor.py --selftest
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:  # openpyxl is only needed for Excel input
    import openpyxl
    from openpyxl.utils import get_column_letter
except Exception:  # pragma: no cover
    openpyxl = None

    def get_column_letter(i: int) -> str:  # minimal fallback
        s = ""
        while i:
            i, rem = divmod(i - 1, 26)
            s = chr(65 + rem) + s
        return s

log = logging.getLogger("table_extractor")

META_COLS = ("_row_kind", "_group", "_src_row")


# =============================================================================
# Configuration
# =============================================================================
@dataclass
class Config:
    wide_merge_frac: float = 0.8          # merge covering >= this share of block width => "wide"
    data_num_frac: float = 0.4            # numeric share of a row's cells to look like data
    note_prefixes: tuple = ("*", "†", "‡", "note", "source", "n.b", "nb:", "nb.", "footnote", "(*)", "# ")
    note_max_len: int = 90                # long single-cell text rows are treated as notes
    total_patterns: tuple = (
        r"\btotals?\b", r"^all$", r"^grand\b", r"\bsub[\s-]?totals?\b", r"^sum$", r"^overall$",
    )
    total_label_max_len: int = 40         # label-only total detection ignores long labels
    placeholders: tuple = ("-", "--", "---", "—", "–", "na", "n/a", "n.a.", "n.a", "nil", "..", "...")
    min_split_text_anchors: int = 3       # header-like row needed to split two tables with no gap
    reconcile_rel_tol: float = 1e-6
    include_hidden_sheets: bool = False
    recalc_missing_cached: bool = True    # use LibreOffice (if present) when formulas have no cached values
    header_sep: str = " | "
    max_header_rows: int = 8


# =============================================================================
# Low-level value helpers
# =============================================================================
_WS = re.compile(r"\s+")
_ERR = re.compile(r"^#(DIV/0!|N/A|NAME\?|NULL!|NUM!|REF!|VALUE!|SPILL!|CALC!)$")
_PLAIN = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_GROUPED = re.compile(r"^[+-]?\d{1,3}(,\d{2,3})+(\.\d+)?$")
_LEADZERO = re.compile(r"^[+-]?0\d")
_CURRENCY = str.maketrans("", "", "$€£₹¥ ")
_INDEX_STR = re.compile(r"^\(?\d{1,3}\)?$")


def clean_text(v: Any) -> Optional[str]:
    """Normalise a cell to a trimmed single-line string, or None if empty."""
    if v is None:
        return None
    if isinstance(v, float):
        if v != v:
            return None
        if v.is_integer():
            v = int(v)
    s = _WS.sub(" ", str(v).replace("\xa0", " ")).strip()
    if not s or _ERR.match(s):
        return None
    return s


def parse_number(v: Any) -> Optional[float]:
    """Return a number for numeric cells / numeric-looking strings, else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return v if (not isinstance(v, float) or math.isfinite(v)) else None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    s = s.translate(_CURRENCY)
    pct = s.endswith("%")
    if pct:
        s = s[:-1]
    if not (_PLAIN.match(s) or _GROUPED.match(s)):
        return None
    if _LEADZERO.match(s) and "." not in s:          # "007" is an identifier, not a number
        return None
    s = s.replace(",", "")
    try:
        x: float = float(s) if any(ch in s for ch in ".eE") else int(s)
    except ValueError:
        return None
    if neg:
        x = -x
    return x / 100 if pct else x


def is_num(v: Any) -> bool:
    return parse_number(v) is not None


def _is_integral(x: Any) -> bool:
    return isinstance(x, int) or (isinstance(x, float) and x.is_integer())


# =============================================================================
# Grid: uniform in-memory representation for xlsx and csv
# =============================================================================
class Grid:
    def __init__(self, val, formula, merges, ws=None, name=""):
        self.val: list[list[Any]] = val
        self.formula: list[list[Optional[str]]] = formula
        self.n_rows = len(val)
        self.n_cols = len(val[0]) if val else 0
        self.merges: list[tuple[int, int, int, int]] = merges   # (r0, c0, r1, c1) zero-based inclusive
        self.ws = ws
        self.name = name
        self.merge_at: dict[tuple[int, int], tuple[int, int, int, int]] = {}
        for m in merges:
            r0, c0, r1, c1 = m
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    self.merge_at[(r, c)] = m

    def mask(self) -> list[list[bool]]:
        """Non-empty mask; merged ranges with a value are filled so they bridge gaps."""
        m = [[v is not None for v in row] for row in self.val]
        for r0, c0, r1, c1 in self.merges:
            if self.val[r0][c0] is not None:
                for r in range(r0, r1 + 1):
                    for c in range(c0, c1 + 1):
                        m[r][c] = True
        return m

    def style(self, r: int, c: int) -> dict:
        """Lazy style lookup (bold / indent) for hierarchy hints."""
        if self.ws is None:
            return {}
        try:
            cell = self.ws.cell(r + 1, c + 1)
            return {"bold": bool(cell.font and cell.font.b),
                    "indent": int(cell.alignment.indent or 0) if cell.alignment else 0}
        except Exception:
            return {}


def _pad_grid(rows: list[list[Any]]) -> list[list[Any]]:
    w = max((len(r) for r in rows), default=0)
    return [list(r) + [None] * (w - len(r)) for r in rows]


def _trim(val: list[list[Any]], formula: list[list[Optional[str]]]):
    last_r = last_c = -1
    for r, row in enumerate(val):
        for c, v in enumerate(row):
            if v is not None or formula[r][c] is not None:
                last_r, last_c = max(last_r, r), max(last_c, c)
    return ([row[: last_c + 1] for row in val[: last_r + 1]],
            [row[: last_c + 1] for row in formula[: last_r + 1]])


# ---------------------------------------------------------------- Excel loading
def _soffice() -> Optional[str]:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _convert_with_soffice(path: Path, fmt: str = "xlsx") -> Optional[Path]:
    exe = _soffice()
    if not exe:
        return None
    out = Path(tempfile.mkdtemp(prefix="tx_"))
    try:
        subprocess.run([exe, "--headless", "--convert-to", fmt, "--outdir", str(out), str(path)],
                       check=True, capture_output=True, timeout=180)
    except Exception as e:  # pragma: no cover
        log.warning("LibreOffice conversion failed for %s: %s", path.name, e)
        return None
    res = out / (path.stem + "." + fmt)
    return res if res.exists() else None


def _formula_text(v: Any) -> Optional[str]:
    if isinstance(v, str) and v.startswith("="):
        return v
    t = getattr(v, "text", None)          # ArrayFormula etc.
    if isinstance(t, str):
        return t if t.startswith("=") else "=" + t
    return None


def load_excel_grids(path: Path, cfg: Config) -> list[tuple[str, Grid, list[str]]]:
    """Return [(sheet_name, Grid, load_warnings)] for every (visible) sheet."""
    if openpyxl is None:
        raise RuntimeError("openpyxl is required for Excel input")
    path = Path(path)
    src = path
    if path.suffix.lower() == ".xls":
        conv = _convert_with_soffice(path, "xlsx")
        if conv is None:
            raise RuntimeError(".xls needs LibreOffice (soffice) to convert, or save the file as .xlsx first")
        src = conv
    keep_vba = src.suffix.lower() == ".xlsm"
    wb_f = openpyxl.load_workbook(src, data_only=False, keep_vba=keep_vba)
    wb_v = openpyxl.load_workbook(src, data_only=True, keep_vba=keep_vba)

    def missing_cached(wf, wv) -> int:
        n = 0
        for ws in wf.worksheets:
            wsv = wv[ws.title]
            for row in ws.iter_rows():
                for c in row:
                    if _formula_text(c.value) and wsv.cell(c.row, c.column).value is None:
                        n += 1
        return n

    notes: list[str] = []
    miss = missing_cached(wb_f, wb_v)
    if miss and cfg.recalc_missing_cached:
        conv = _convert_with_soffice(src, "xlsx")
        if conv:
            wb_v = openpyxl.load_workbook(conv, data_only=True)
            left = missing_cached(wb_f, wb_v)
            notes.append(f"{miss} formula cells had no cached value; recalculated via LibreOffice ({left} still empty)")
        else:
            notes.append(f"{miss} formula cells have no cached value and LibreOffice is unavailable; they load as empty")

    out = []
    for ws_f in wb_f.worksheets:
        if ws_f.sheet_state != "visible" and not cfg.include_hidden_sheets:
            continue
        ws_v = wb_v[ws_f.title]
        val = [[clean_cell(v) for v in row] for row in ws_v.iter_rows(values_only=True)]
        frm = [[_formula_text(v) for v in row] for row in ws_f.iter_rows(values_only=True)]
        val, frm = _pad_grid(val), _pad_grid(frm)
        R = min(len(val), len(frm))
        val, frm = val[:R], frm[:R]
        val, frm = _trim(val, frm)
        if not val:
            out.append((ws_f.title, Grid([], [], [], ws_f, ws_f.title), notes))
            continue
        R, C = len(val), len(val[0])
        merges = []
        for m in ws_f.merged_cells.ranges:
            r0, c0, r1, c1 = m.min_row - 1, m.min_col - 1, min(m.max_row, R) - 1, min(m.max_col, C) - 1
            if r0 < R and c0 < C:
                merges.append((r0, c0, r1, c1))
        out.append((ws_f.title, Grid(val, frm, merges, ws_f, ws_f.title), notes))
    return out


def clean_cell(v: Any) -> Any:
    """Normalise a raw cell: strip text, blank -> None, keep numbers/dates as they are."""
    if v is None:
        return None
    if isinstance(v, str):
        s = _WS.sub(" ", v.replace("\xa0", " ")).strip()
        return None if (not s or _ERR.match(s)) else s
    if isinstance(v, float) and v != v:
        return None
    return v


# ---------------------------------------------------------------- CSV loading
def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _sniff_delimiter(text: str, suffix: str) -> str:
    if suffix == ".tsv":
        return "\t"
    lines = [ln for ln in text.splitlines()[:60] if ln.strip()]
    best, best_score = ",", -1.0
    for d in (",", ";", "\t", "|"):
        counts = [ln.count(d) for ln in lines]
        if not counts or max(counts) == 0:
            continue
        mode = max(set(counts), key=counts.count)
        score = (counts.count(mode) / len(counts)) * (1 if mode > 0 else 0) + 0.01 * mode
        if mode > 0 and score > best_score:
            best, best_score = d, score
    return best


def load_csv_grid(path: Path, cfg: Config) -> Grid:
    text = _decode(Path(path).read_bytes())
    delim = _sniff_delimiter(text, Path(path).suffix.lower())
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return grid_from_rows(rows, name=Path(path).stem)


def grid_from_rows(rows: list[list[Any]], name: str = "") -> Grid:
    """Build a Grid from raw rows (strings get numeric parsing; no merges/formulas)."""
    val = []
    for row in rows:
        out = []
        for v in row:
            v = clean_cell(v)
            if isinstance(v, str):
                # Preserve parenthesized column-index labels such as (1), (2), ...
                # so row profiling can identify and discard the index row.
                if not _INDEX_STR.match(v.strip()):
                    n = parse_number(v)
                    v = n if n is not None else v
            out.append(v)
        val.append(out)
    val = _pad_grid(val)
    frm = [[None] * len(val[0]) for _ in val] if val else []
    val, frm = _trim(val, frm)
    return Grid(val, frm, [], None, name)


# =============================================================================
# Row profiling
# =============================================================================
@dataclass
class RowInfo:
    r: int
    anchors: list                  # [(col, value)]
    n_anchor: int = 0
    n_num: int = 0
    n_ph: int = 0
    n_text: int = 0
    merge_w: int = 1               # merge width of the single anchor (if n_anchor == 1)
    wide: bool = False
    is_index: bool = False
    is_year: bool = False

    @property
    def blank(self) -> bool:
        return self.n_anchor == 0


def _is_ph(v: Any, cfg: Config) -> bool:
    return isinstance(v, str) and v.strip().lower() in cfg.placeholders


def row_info(grid: Grid, r: int, c0: int, c1: int, cfg: Config) -> RowInfo:
    anchors = [(c, grid.val[r][c]) for c in range(c0, c1 + 1) if grid.val[r][c] is not None]
    inf = RowInfo(r=r, anchors=anchors, n_anchor=len(anchors))
    for _, v in anchors:
        if _is_ph(v, cfg):
            inf.n_ph += 1
        elif is_num(v):
            inf.n_num += 1
        else:
            inf.n_text += 1
    width = c1 - c0 + 1
    if inf.n_anchor == 1:
        c = anchors[0][0]
        m = grid.merge_at.get((r, c))
        inf.merge_w = (m[3] - m[1] + 1) if m else 1
        inf.wide = width >= 3 and inf.merge_w >= cfg.wide_merge_frac * width
    # index row: consecutive integers 0/1.. or "(1)(2)(3)"
    if inf.n_anchor >= 3:
        seq = []
        for _, v in sorted(anchors):
            if isinstance(v, str) and _INDEX_STR.match(v.strip()):
                seq.append(int(v.strip().strip("()")))
            elif not isinstance(v, bool) and isinstance(v, (int, float)) and _is_integral(v):
                seq.append(int(v))
            else:
                seq = []
                break
        inf.is_index = bool(seq) and seq[0] in (0, 1) and all(b - a == 1 for a, b in zip(seq, seq[1:]))
    # year header row: 2019 2020 2021 ...
    nums = [parse_number(v) for _, v in anchors if is_num(v) and not _is_ph(v, cfg)]
    if len(nums) >= 3 and len(nums) / inf.n_anchor >= 0.6:
        if all(_is_integral(x) and 1900 <= x <= 2100 for x in nums) and all(b >= a for a, b in zip(nums, nums[1:])):
            inf.is_year = True
    return inf


def _data_like(inf: RowInfo, width: int, cfg: Config, loose: bool = False) -> bool:
    if inf.blank or inf.is_index or inf.is_year:
        return False
    if inf.n_num >= 1 and inf.n_num / inf.n_anchor >= cfg.data_num_frac and (inf.n_anchor >= 2 or width == 1):
        return True
    if loose and inf.n_num + inf.n_ph >= 2 and (inf.n_num + inf.n_ph) / inf.n_anchor >= 0.5:
        return True
    return False


def looks_like_note(text: str, cfg: Config) -> bool:
    t = text.strip().lower()
    return any(t.startswith(p) for p in cfg.note_prefixes) or len(t) > cfg.note_max_len


# =============================================================================
# Block analysis (titles / header / index / data start)
# =============================================================================
@dataclass
class Analysis:
    title_rows: list = field(default_factory=list)
    header_rows: list = field(default_factory=list)
    index_rows: list = field(default_factory=list)
    pre_sections: list = field(default_factory=list)
    data_start: Optional[int] = None
    text_mode: bool = False
    infos: dict = field(default_factory=dict)


def _uniform_banner_text(inf: RowInfo, width: int) -> Optional[str]:
    """Fill-expanded title/id banners (same label repeated across columns).

    openpyxl often materialises a merged title as the same string in every
    cell of the row. Those rows are not ``n_anchor == 1``, so the single-cell
    title rule misses them unless we recognise the uniform text pattern.
    """
    if width < 3 or inf.n_num > 0 or inf.n_anchor <= 0:
        return None
    texts = []
    for _, v in inf.anchors:
        t = clean_text(v)
        if t:
            texts.append(t)
    if not texts:
        return None
    # Require most of the row to be filled with the same label (not a sparse stub).
    if inf.n_anchor < max(2, int(0.5 * width)):
        return None
    uniq = {t.lower() for t in texts}
    if len(uniq) != 1:
        return None
    return texts[0]


def _looks_like_stub_section_row(inf: RowInfo, width: int, denser_header: Optional[RowInfo]) -> bool:
    """True for mid-table banners like ``A | Number`` / ``B | Percentage``.

    These sit under real multi-level headers (dense leaf row above) but only
    label the stub columns. Treating them as header leaves produces paths such
    as ``('Sl. No.', 'A')`` and drops the banner from the body.
    """
    if inf.n_num > 0 or inf.n_ph > 0 or inf.n_anchor <= 0:
        return False
    # Classic single-cell section / category banner.
    if inf.n_anchor == 1:
        return True
    if denser_header is None or width < 4:
        return False
    # Sparse stub-side labels under a denser leaf-header row.
    if inf.n_anchor > 2:
        return False
    if denser_header.n_anchor < max(3, inf.n_anchor * 2):
        return False
    max_c = max((c for c, _ in inf.anchors), default=0)
    # Anchors only on the left half (under Sl. No. / Religion-style stubs).
    return max_c <= max(1, (width - 1) // 2)


def analyze(grid: Grid, r0: int, r1: int, c0: int, c1: int, cfg: Config, fallback: bool = False) -> Analysis:
    width = c1 - c0 + 1
    infos = {r: row_info(grid, r, c0, c1, cfg) for r in range(r0, r1 + 1)}
    an = Analysis(infos=infos)
    nz = [r for r in range(r0, r1 + 1) if not infos[r].blank]

    k = 0
    while k < len(nz):
        inf = infos[nz[k]]
        single = (
            inf.n_anchor == 1
            and width >= 3
            and inf.n_num == 0
            and (inf.wide or inf.merge_w == 1)
        )
        if single or _uniform_banner_text(inf, width):
            an.title_rows.append(nz[k])
            k += 1
        else:
            break
    rest = nz[k:]

    ds = next((r for r in rest if _data_like(infos[r], width, cfg)), None)
    if ds is not None:
        pre = [r for r in rest if r < ds]
        an.index_rows = [r for r in pre if infos[r].is_index]
        an.header_rows = [r for r in pre if not infos[r].is_index]
        # Peel trailing section banners out of the header band (single-cell or
        # sparse stub labels like "A | Number" under Births/Deaths leaf headers).
        while len(an.header_rows) > 1:
            last = an.header_rows[-1]
            denser = infos[an.header_rows[-2]] if len(an.header_rows) >= 2 else None
            if not _looks_like_stub_section_row(infos[last], width, denser):
                break
            if infos[last].n_num > 0:
                break
            an.pre_sections.insert(0, an.header_rows.pop())
        an.data_start = ds
    else:
        an.index_rows = [r for r in rest if infos[r].is_index]
        an.header_rows = [r for r in rest if not infos[r].is_index]
        if fallback and len(rest) >= 2:                    # all-text table: first row = header
            an.header_rows, an.index_rows, an.pre_sections = [rest[0]], [], []
            an.data_start = rest[1]
            an.text_mode = True
    return an


def _embedded_split_start(an: Analysis, cfg: Config, width: int) -> Optional[int]:
    """Row where a second table starts inside one blank-free band (new, different header)."""
    if an.data_start is None:
        return None
    infos = an.infos
    htexts = {t.lower() for r in an.header_rows for _, v in infos[r].anchors if (t := clean_text(v))}
    nz = [r for r in sorted(infos) if r > an.data_start and not infos[r].blank]
    for i, r in enumerate(nz):
        inf = infos[r]
        if inf.n_anchor >= cfg.min_split_text_anchors and inf.n_num == 0 and inf.n_ph == 0:
            texts = {t.lower() for _, v in inf.anchors if (t := clean_text(v))}
            if texts and len(texts & htexts) / len(texts) < 0.5:
                if any(_data_like(infos[x], width, cfg) for x in nz[i + 1: i + 7]):
                    start, j = r, i - 1
                    while j >= 0 and infos[nz[j]].n_num == 0:
                        start = nz[j]
                        j -= 1
                    return start
    return None


# =============================================================================
# Sheet segmentation
# =============================================================================
def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def _col_extent(mask, a: int, b: int) -> tuple[int, int]:
    cols = [c for c in range(len(mask[0])) if any(mask[r][c] for r in range(a, b + 1))]
    return min(cols), max(cols)


@dataclass
class Block:
    r0: int
    r1: int
    c0: int
    c1: int
    an: Analysis
    titles: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def segment_sheet(grid: Grid, cfg: Config) -> list[Block]:
    if grid.n_rows == 0:
        return []
    mask = grid.mask()
    items: list[list] = []
    for a, b in _runs([any(row) for row in mask]):
        c0, c1 = _col_extent(mask, a, b)
        items.append([a, b, c0, c1, analyze(grid, a, b, c0, c1, cfg)])

    # 1) glue "header-only" bands to the following "data-only" band (e.g. blank row after an index row)
    i = 0
    glued: list[list] = []
    while i < len(items):
        a, b, c0, c1, an = items[i]
        if an.data_start is None and an.header_rows and i + 1 < len(items):
            a2, b2, c02, c12, an2 = items[i + 1]
            if (an2.data_start is not None and not an2.header_rows and not an2.title_rows
                    and not an2.index_rows and not an2.pre_sections):
                cc0, cc1 = min(c0, c02), max(c1, c12)
                items[i + 1] = [a, b2, cc0, cc1, analyze(grid, a, b2, cc0, cc1, cfg)]
                i += 1
                continue
        glued.append(items[i])
        i += 1
    items = glued

    # 1b) a band with no title/header of its own,
    # directly below a table with (nearly) the same columns,
    # is a continuation of that table
    cont: list[list] = []
    for it in items:
        a, b, c0, c1, an = it
        if cont and an.data_start is not None and not (
            an.header_rows or an.title_rows
            or an.index_rows or an.pre_sections
        ):
            pa, pb, pc0, pc1, pan = cont[-1]
            overlap = min(c1, pc1) - max(c0, pc0) + 1
            if (
                pan.data_start is not None
                and a - pb - 1 <= 3
                and overlap >= 0.8 * max(c1 - c0 + 1, pc1 - pc0 + 1)
            ):
                cc0, cc1 = min(c0, pc0), max(c1, pc1)
                cont[-1] = [
                    pa, b, cc0, cc1,
                    analyze(grid, pa, b, cc0, cc1, cfg),
                ]
                continue
        cont.append(it)
    items = cont

    # 2) split bands that hold two tables with no blank row between them
    work, stack = [], list(reversed(items))
    while stack:
        a, b, c0, c1, an = stack.pop()
        s = _embedded_split_start(an, cfg, c1 - c0 + 1)
        if s is not None and s > a:
            stack.append([s, b, c0, c1, analyze(grid, s, b, c0, c1, cfg)])
            stack.append([a, s - 1, c0, c1, analyze(grid, a, s - 1, c0, c1, cfg)])
        else:
            work.append([a, b, c0, c1, an])

    # 3) split side-by-side tables (only if every part is a valid table on its own)
    split: list[list] = []
    for a, b, c0, c1, an in work:
        parts = _col_parts(grid, mask, a, b, c0, c1)
        if len(parts) >= 2:
            ans = [analyze(grid, a, b, p0, p1, cfg) for p0, p1 in parts]
            if all(x.data_start is not None for x in ans):
                lead = _lead_titles(grid, a, b, c0, c1)
                for (p0, p1), x in zip(parts, ans):
                    blk = [a, b, p0, p1, x]
                    blk.append(lead if not x.title_rows else [])
                    split.append(blk)
                continue
        split.append([a, b, c0, c1, an, []])

    # 4) turn items into table blocks / free-text (titles & notes)
    blocks: list[Block] = []
    pending: list[str] = []
    for a, b, c0, c1, an, inherit in split:
        if an.data_start is None:
            an_fb = analyze(grid, a, b, c0, c1, cfg, fallback=True)
            multi = [r for r in an_fb.infos if an_fb.infos[r].n_anchor >= 2]
            if an_fb.data_start is not None and len(multi) >= 2:
                an = an_fb
            else:
                for r in range(a, b + 1):
                    t = " ".join(clean_text(v) or "" for _, v in an.infos[r].anchors).strip()
                    if t:
                        if blocks and looks_like_note(t, cfg):
                            blocks[-1].notes.append(t)
                        else:
                            pending.append(t)
                continue
        titles = list(pending) + list(inherit)
        pending = []
        for r in an.title_rows:
            t = clean_text(grid.val[r][an.infos[r].anchors[0][0]])
            if t:
                titles.append(t)
        blocks.append(Block(a, b, c0, c1, an, titles=titles))
    if pending and blocks:
        blocks[-1].notes.extend(pending)
    return blocks


def _col_parts(grid: Grid, mask, a: int, b: int, c0: int, c1: int) -> list[tuple[int, int]]:
    body = [r for r in range(a, b + 1) if sum(1 for c in range(c0, c1 + 1) if grid.val[r][c] is not None) > 1]
    if not body:
        return [(c0, c1)]
    flags = [any(mask[r][c] for r in body) for c in range(c0, c1 + 1)]
    return [(c0 + s, c0 + e) for s, e in _runs(flags)]


def _lead_titles(grid: Grid, a: int, b: int, c0: int, c1: int) -> list[str]:
    out = []
    for r in range(a, b + 1):
        anchors = [(c, grid.val[r][c]) for c in range(c0, c1 + 1) if grid.val[r][c] is not None]
        if len(anchors) == 1 and not is_num(anchors[0][1]):
            out.append(clean_text(anchors[0][1]) or "")
        else:
            break
    return [t for t in out if t]


# =============================================================================
# Header flattening
# =============================================================================
def build_header_paths(grid: Grid, an: Analysis, c0: int, c1: int, cfg: Config) -> list[tuple[str, ...]]:
    ncols = c1 - c0 + 1
    rows = an.header_rows
    if not rows:
        return [() for _ in range(ncols)]
    hrows = set(rows)
    H: list[list[Optional[str]]] = []
    for r in rows:
        line = []
        for c in range(c0, c1 + 1):
            v = grid.val[r][c]
            if v is None and (r, c) in grid.merge_at:           # expand merged spans (anchor must be a header cell)
                mr0, mc0, _, _ = grid.merge_at[(r, c)]
                if mr0 in hrows:
                    v = grid.val[mr0][mc0]
            line.append(clean_text(v))
        H.append(line)
    leaf = H[-1]
    for i in range(len(H) - 1):                                  # fill upper levels to the right
        start = None
        for j in range(ncols):
            if H[i][j] is not None:
                start = j
                continue
            if start is None or leaf[j] is None:
                start = None if leaf[j] is None else start
                continue
            if leaf[j] == leaf[start]:                           # leaf pattern restarts => new (unnamed) group
                start = None
                continue
            H[i][j] = H[i][start]
    paths = []
    for j in range(ncols):
        p: list[str] = []
        for i in range(len(H)):
            t = H[i][j]
            if t and (not p or p[-1].lower() != t.lower()):
                p.append(t)
        paths.append(tuple(p))
    return paths


def flatten_names(paths: list[tuple[str, ...]], c0: int, sep: str) -> list[str]:
    names, seen = [], {}
    for j, p in enumerate(paths):
        n = sep.join(p) if p else f"col_{get_column_letter(c0 + j + 1)}"
        if n in seen:
            seen[n] += 1
            n = f"{n}.{seen[n]}"
        else:
            seen[n] = 1
        names.append(n)
    return names


# =============================================================================
# Row classification, totals, stub columns
# =============================================================================
def classify_rows(grid: Grid, blk: Block, cfg: Config) -> dict[int, tuple[str, Optional[str]]]:
    an, infos = blk.an, blk.an.infos
    width = blk.c1 - blk.c0 + 1
    htexts = {t.lower() for r in an.header_rows for _, v in infos[r].anchors if (t := clean_text(v))}
    nz = [r for r in range(an.data_start, blk.r1 + 1) if not infos[r].blank]
    kinds: dict[int, tuple[str, Optional[str]]] = {}
    for i, r in enumerate(nz):
        inf = infos[r]
        nxt = infos[nz[i + 1]] if i + 1 < len(nz) else None
        text = " ".join(clean_text(v) or "" for _, v in inf.anchors).strip()
        if an.text_mode:
            # All-text tables have no numeric signal. Suppress repeated copies
            # of the detected header instead of emitting them as data records.
            row_texts = [clean_text(v) for _, v in inf.anchors]
            header_texts = [
                clean_text(grid.val[hr][c])
                for hr in an.header_rows
                for c in range(blk.c0, blk.c1 + 1)
                if grid.val[hr][c] is not None
            ]
            normalized_row = [x.lower() for x in row_texts if x]
            normalized_header = [x.lower() for x in header_texts if x]
            if normalized_row == normalized_header:
                kinds[r] = ("header_repeat", None)
            elif inf.n_anchor == 1 and (inf.wide or looks_like_note(text, cfg)):
                kinds[r] = ("note", text)
            else:
                kinds[r] = ("data", None)
        elif _data_like(inf, width, cfg, loose=True) or inf.n_num >= 1:
            kinds[r] = ("data", None)
        elif inf.n_anchor == 1:
            if looks_like_note(text, cfg):
                kinds[r] = ("note", text)
            elif nxt is not None and (_data_like(nxt, width, cfg, loose=True) or nxt.n_num >= 1):
                kinds[r] = ("section", text)
            else:
                kinds[r] = ("note", text)
        else:
            texts = {t.lower() for _, v in inf.anchors if (t := clean_text(v))}
            if texts and len(texts & htexts) / len(texts) >= 0.5:
                kinds[r] = ("header_repeat", None)
            elif nxt is not None and nxt.n_num >= 1:
                kinds[r] = ("section", text)
            else:
                kinds[r] = ("note", text)
    return kinds


_AGG_RANGE = re.compile(r"\$?([A-Z]{1,3})\$?(\d+):\$?([A-Z]{1,3})\$?(\d+)")


def _formula_is_col_aggregate(f: Optional[str]) -> bool:
    if not f or not re.search(r"(SUM|SUBTOTAL|AGGREGATE)\s*\(", f, re.I):
        return False
    return any(m.group(1) == m.group(3) and int(m.group(4)) > int(m.group(2)) for m in _AGG_RANGE.finditer(f))


def _is_serial(vals: list[float]) -> bool:
    ints = [int(v) for v in vals if _is_integral(v)]
    if len(ints) < 2 or len(ints) / len(vals) < 0.8:
        return False
    ok = sum(1 for a, b in zip(ints, ints[1:]) if b == a + 1 or b in (0, 1))
    return ok / (len(ints) - 1) >= 0.7


def detect_stub_columns(grid: Grid, data_rows: list[int], c0: int, c1: int, cfg: Config) -> list[int]:
    """Leading label/serial columns (a prefix of the block)."""
    stub = []
    for c in range(c0, c1 + 1):
        vals = [grid.val[r][c] for r in data_rows if grid.val[r][c] is not None]
        if not vals:
            if stub:
                stub.append(c)          # blank spacer inside the label area
                continue
            break
        nums = [parse_number(v) for v in vals if is_num(v) and not _is_ph(v, cfg)]
        texts = [v for v in vals if not is_num(v) and not _is_ph(v, cfg)]
        if len(texts) / len(vals) >= 0.5 or (nums and _is_serial(nums)):
            stub.append(c)
        else:
            break
    while stub and not any(grid.val[r][stub[-1]] is not None for r in data_rows):
        stub.pop()
    return stub


def _num_rows(grid: Grid, rows: list[int], cols: list[int], cfg: Config) -> dict[int, dict[int, float]]:
    out = {}
    for r in rows:
        d = {}
        for c in cols:
            v = grid.val[r][c]
            if v is not None and not _is_ph(v, cfg):
                x = parse_number(v)
                if x is not None:
                    d[c] = x
        out[r] = d
    return out


def _reconcile(row: dict, scope: list[dict], cfg: Config) -> tuple[float, int]:
    """(share of columns where row == sum(scope), number of columns compared)."""
    ok = n = 0
    for c, v in row.items():
        exp = sum(s.get(c, 0.0) for s in scope)
        if exp == 0 and v == 0:
            continue
        n += 1
        if abs(v - exp) <= cfg.reconcile_rel_tol * max(1.0, abs(exp)) + 1e-9:
            ok += 1
    return (ok / n if n else 0.0), n


def _stub_label_is_total_like(grid: Grid, r: int, stub_cols: list[int], cfg: Config) -> bool:
    """True when a stub cell (including text merges) looks like Total / All / Grand total."""
    pats = [re.compile(p, re.I) for p in cfg.total_patterns]
    for c in stub_cols:
        t = clean_text(_cell_value(grid, r, c))
        if t and len(t) <= cfg.total_label_max_len and any(p.search(t) for p in pats):
            return True
    return False


def detect_totals(grid: Grid, data_rows: list[int], stub_cols: list[int], num_cols: list[int],
                  cfg: Config) -> tuple[dict[int, str], list[str]]:
    nums = _num_rows(grid, data_rows, num_cols, cfg)
    warns: list[str] = []

    def label_hit(r: int) -> bool:
        # Use merge-aware stub text so Total/All spanning M/F/O are all flagged.
        return _stub_label_is_total_like(grid, r, stub_cols, cfg)

    def formula_hit(r: int) -> bool:
        fs = [grid.formula[r][c] for c in num_cols if grid.formula[r][c]]
        return bool(fs) and sum(_formula_is_col_aggregate(f) for f in fs) / len(fs) >= 0.5

    since_prev: list[int] = []
    all_rows: list[int] = []
    flagged: list[tuple[int, bool, bool, bool]] = []     # (row, matches_prev, matches_all, had_prior_total)
    for r in data_rows:
        hit = label_hit(r) or formula_hit(r)
        by_sum = False
        if not hit and len(since_prev) >= 2:
            frac, n = _reconcile(nums[r], [nums[x] for x in since_prev], cfg)
            by_sum = n >= 2 and frac == 1.0
        if hit or by_sum:
            fp, np_ = _reconcile(nums[r], [nums[x] for x in since_prev], cfg) if since_prev else (0.0, 0)
            fa, na = _reconcile(nums[r], [nums[x] for x in all_rows], cfg) if all_rows else (0.0, 0)
            m_prev, m_all = np_ >= 1 and fp >= 0.8, na >= 1 and fa >= 0.8
            flagged.append((r, m_prev, m_all, bool(flagged)))
            if not (m_prev or m_all) and (nums[r]):
                warns.append(f"total-like row {r + 1} does not equal the sum of the rows above (best-effort check)")
            since_prev = []
        else:
            since_prev.append(r)
            all_rows.append(r)
    kinds: dict[int, str] = {}
    flagged_rows = {f[0] for f in flagged}
    for r, m_prev, m_all, had_prior in flagged:
        later_data = any(x > r and x not in flagged_rows for x in data_rows)
        kinds[r] = "subtotal" if ((m_prev and not m_all and had_prior) or later_data) else "total"
    return kinds, warns


# =============================================================================
# Result object
# =============================================================================
@dataclass
class ExtractedTable:
    source_file: str
    sheet: str
    table_index: int
    title: str
    notes: list
    cell_range: str
    header_range: Optional[str]
    header_paths: list
    columns: list
    col_letters: list
    stub_columns: list
    derived_columns: list
    df: pd.DataFrame
    warnings: list
    confidence: float

    @property
    def table_id(self) -> str:
        return f"{Path(self.source_file).stem}::{self.sheet}::{self.table_index}"

    def data_only(
        self,
        include_totals: bool = False,
        keep_meta: bool = False,
        include_sections: bool = False,
    ) -> pd.DataFrame:
        d = self.df
        if not include_totals:
            keep = {"data"}
            if include_sections:
                keep.add("section")
            d = d[d["_row_kind"].isin(keep)]
        if not keep_meta:
            d = d.drop(columns=[c for c in META_COLS if c in d.columns])
        return d.reset_index(drop=True)

    def multiindex_df(self, include_totals: bool = False) -> pd.DataFrame:
        d = self.data_only(include_totals=include_totals).copy()
        depth = max((len(p) for p in self.header_paths), default=1) or 1
        tuples = [tuple(list(p) + [""] * (depth - len(p))) if p else (c,) + ("",) * (depth - 1)
                  for p, c in zip(self.header_paths, self.columns)]
        d.columns = pd.MultiIndex.from_tuples(tuples)
        return d

    def to_long(self, include_totals: bool = False, dropna: bool = True) -> pd.DataFrame:
        d = self.data_only(include_totals=include_totals, keep_meta=True)
        val_cols = [c for c in self.columns if c not in self.stub_columns]
        ids = list(self.stub_columns) + [m for m in META_COLS if m in d.columns]
        if not val_cols:
            return d[ids]
        long = d.melt(id_vars=ids, value_vars=val_cols, var_name="column", value_name="value")
        paths = dict(zip(self.columns, self.header_paths))
        letters = dict(zip(self.columns, self.col_letters))
        depth = max(len(paths[c]) for c in val_cols)
        for k in range(depth):
            long[f"level_{k}"] = long["column"].map(lambda c, k=k: paths[c][k] if k < len(paths[c]) else None)
        long["_src_cell"] = long["column"].map(letters) + long["_src_row"].astype(str)
        if dropna:
            long = long[long["value"].notna()]
        return long.reset_index(drop=True)

    def fingerprint(self) -> str:
        d = self.data_only()
        h = hashlib.sha1()
        h.update("|".join("/".join(p) for p in self.header_paths).encode())
        h.update(d.round(6).to_csv(index=False).encode())
        return h.hexdigest()

    def summary(self) -> str:
        n = int((self.df["_row_kind"] == "data").sum())
        return (f"[{self.table_id}] {self.cell_range} | {n} data rows x {len(self.columns)} cols | "
                f"conf={self.confidence:.2f} | {self.title or '(no title)'}")

    def manifest(self) -> dict:
        return {
            "table_id": self.table_id, "source_file": self.source_file, "sheet": self.sheet,
            "title": self.title, "notes": self.notes, "range": self.cell_range, "header_range": self.header_range,
            "columns": self.columns, "header_paths": [list(p) for p in self.header_paths],
            "stub_columns": self.stub_columns, "derived_columns": self.derived_columns,
            "n_data_rows": int((self.df["_row_kind"] == "data").sum()),
            "n_total_rows": int((self.df["_row_kind"] != "data").sum()),
            "confidence": round(self.confidence, 3), "warnings": self.warnings,
            "fingerprint": self.fingerprint(),
        }


# =============================================================================
# Table construction
# =============================================================================
def _ref(r0: int, c0: int, r1: int, c1: int) -> str:
    return f"{get_column_letter(c0 + 1)}{r0 + 1}:{get_column_letter(c1 + 1)}{r1 + 1}"


def _cell_value(grid: Grid, r: int, c: int) -> Any:
    v = grid.val[r][c]
    if v is None and (r, c) in grid.merge_at:               # expand text merges only (numbers aren't duplicated)
        mr0, mc0, _, _ = grid.merge_at[(r, c)]
        a = grid.val[mr0][mc0]
        if a is not None and not is_num(a):
            return a
    return v


def _finalize_column(values: list, is_stub: bool, cfg: Config, name: str, warns: list):
    kinds = []
    for v in values:
        if v is None:
            kinds.append("n")
        elif _is_ph(v, cfg):
            kinds.append("p")
        elif is_num(v):
            kinds.append("d")
        else:
            kinds.append("t")
    n_d, n_t = kinds.count("d"), kinds.count("t")
    if n_d + n_t == 0:
        return pd.Series([None] * len(values), dtype="object")
    if is_stub:
        if n_t == 0:
            nums = [None if k in "np" else parse_number(v) for v, k in zip(values, kinds)]
            if all(x is None or _is_integral(x) for x in nums):
                return pd.Series([None if x is None else int(x) for x in nums], dtype="Int64")
            return pd.Series(nums, dtype="float64")
        return pd.Series([None if k in "n" else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
                          for v, k in zip(values, kinds)], dtype="object")
    if n_t == 0 or n_d / (n_d + n_t) >= 0.9:
        if n_t:
            warns.append(f"column '{name}': {n_t} non-numeric value(s) coerced to NaN")
        nums = [parse_number(v) if k == "d" else None for v, k in zip(values, kinds)]
        if all(x is None or _is_integral(x) for x in nums):
            return pd.Series([None if x is None else int(x) for x in nums], dtype="Int64")
        return pd.Series(nums, dtype="float64")
    return pd.Series([None if k == "n" else (str(v) if not isinstance(v, (str, datetime, date)) else v)
                      for v, k in zip(values, kinds)], dtype="object")


def build_table(grid: Grid, source: str, sheet: str, idx: int, blk: Block, cfg: Config) -> Optional[ExtractedTable]:
    an, c0, c1 = blk.an, blk.c0, blk.c1
    warns: list[str] = []
    conf = 1.0

    paths = build_header_paths(grid, an, c0, c1, cfg)
    names = flatten_names(paths, c0, cfg.header_sep)
    if not an.header_rows:
        warns.append("no header row detected; generic column names used")
        conf -= 0.25
    if len(an.header_rows) > cfg.max_header_rows:
        warns.append(f"{len(an.header_rows)} header rows detected (suspicious)")
        conf -= 0.2
    if an.text_mode:
        warns.append("no numeric rows found; first row used as header (text-table fallback)")
        conf -= 0.3

    kinds = classify_rows(grid, blk, cfg)
    notes = list(blk.notes)
    data_rows = [r for r, (k, _) in kinds.items() if k == "data"]
    if not data_rows:
        return None
    cols = list(range(c0, c1 + 1))

    stub = detect_stub_columns(grid, data_rows, c0, c1, cfg)
    num_cols = [c for c in cols if c not in stub]
    tot, tw = detect_totals(grid, data_rows, stub, num_cols, cfg)
    warns.extend(tw)
    conf -= min(0.3, 0.05 * len(tw))

    plain = [r for r in data_rows if r not in tot]
    # leaf label = right-most stub column that is complete; columns left of it are parents (fill down)
    def fill_ratio(c):
        return sum(1 for r in plain if _cell_value(grid, r, c) is not None) / max(1, len(plain))
    leaf = next((c for c in reversed(stub) if fill_ratio(c) >= 0.98), None)
    parents = [c for c in stub if leaf is not None and c < leaf and fill_ratio(c) < 1.0]

    sections: list[str] = []
    group_for: dict[int, str] = {}
    prev_kind = None
    rows_out = []
    # Pre-data section banners (e.g. "A | Number") peeled from the header band.
    for r in list(an.pre_sections):
        t = clean_text(" ".join(clean_text(v) or "" for _, v in an.infos[r].anchors))
        if not t:
            continue
        sections = sections + [t] if prev_kind == "section" else [t]
        prev_kind = "section"
        rec = {c: _cell_value(grid, r, c) for c in cols}
        rows_out.append((r, "section", " > ".join(sections), rec))
    ordered = sorted(kinds)
    carry: dict[int, Any] = {}
    for r in ordered:
        k, label = kinds[r]
        if k == "section":
            sections = sections + [label] if prev_kind == "section" else [label]
            prev_kind = "section"
            # Keep mid-table banners (e.g. "B | Percentage") as visible rows.
            rec = {c: _cell_value(grid, r, c) for c in cols}
            rows_out.append((r, "section", " > ".join(sections), rec))
            continue
        prev_kind = k
        if k == "note":
            notes.append(label)
            continue
        if k != "data":
            continue
        rec = {c: _cell_value(grid, r, c) for c in cols}
        kind = tot.get(r, "data")
        # Do not fill parent stubs into Total/All (or other summary) rows, and
        # clear carry so a prior serial/label cannot leak past the boundary.
        summary = kind != "data" or _stub_label_is_total_like(grid, r, stub, cfg)
        if not summary:
            for c in parents:
                if rec[c] is None and c in carry:
                    rec[c] = carry[c]
                elif rec[c] is not None:
                    carry[c] = rec[c]
        else:
            carry.clear()
        rows_out.append((r, kind, " > ".join(sections), rec))

    series = {}
    for c, name in zip(cols, names):
        series[name] = _finalize_column([rec[c] for _, _, _, rec in rows_out], c in stub, cfg, name, warns)
    df = pd.DataFrame(series)
    df["_row_kind"] = [k for _, k, _, _ in rows_out]
    df["_group"] = [g or None for _, _, g, _ in rows_out]
    df["_src_row"] = [r + 1 for r, _, _, _ in rows_out]

    # drop columns that are entirely empty and have no header
    drop = [n for c, n, p in zip(cols, names, paths) if not p and df[n].isna().all()]
    if drop:
        keep_idx = [i for i, n in enumerate(names) if n not in drop]
        df = df.drop(columns=drop)
        names = [names[i] for i in keep_idx]
        paths = [paths[i] for i in keep_idx]
        cols = [cols[i] for i in keep_idx]
        stub = [c for c in stub if c in cols]
    if len(set(p for p in paths if p)) < len([p for p in paths if p]):
        warns.append("duplicate header paths detected")
        conf -= 0.1

    derived = []
    for c, n in zip(cols, names):
        if c in stub:
            continue
        fr = [grid.formula[r][c] is not None for r, k, _, _ in rows_out if k == "data"]
        if fr and sum(fr) / len(fr) >= 0.8:
            derived.append(n)

    title = " - ".join(dict.fromkeys(blk.titles))
    hdr_range = _ref(an.header_rows[0], c0, an.header_rows[-1], c1) if an.header_rows else None
    return ExtractedTable(
        source_file=source, sheet=sheet, table_index=idx, title=title, notes=notes,
        cell_range=_ref(blk.r0, c0, blk.r1, c1), header_range=hdr_range,
        header_paths=paths, columns=names, col_letters=[get_column_letter(c + 1) for c in cols],
        stub_columns=[names[cols.index(c)] for c in stub], derived_columns=derived,
        df=df, warnings=warns, confidence=max(0.0, conf),
    )


# =============================================================================
# Public API
# =============================================================================
def extract_grid(grid: Grid, source: str = "", sheet: str = "", cfg: Optional[Config] = None) -> list[ExtractedTable]:
    cfg = cfg or Config()
    out = []
    for blk in segment_sheet(grid, cfg):
        t = build_table(grid, source, sheet, len(out) + 1, blk, cfg)
        if t is not None:
            out.append(t)
    return out


def extract_file(path: str | Path, cfg: Optional[Config] = None) -> list[ExtractedTable]:
    cfg = cfg or Config()
    path = Path(path)
    ext = path.suffix.lower()
    tables: list[ExtractedTable] = []
    if ext in (".xlsx", ".xlsm", ".xltx", ".xltm", ".xls"):
        for sheet, grid, load_notes in load_excel_grids(path, cfg):
            ts = extract_grid(grid, str(path), sheet, cfg)
            for t in ts:
                t.warnings = load_notes + t.warnings
            tables.extend(ts)
    elif ext in (".csv", ".tsv", ".txt"):
        grid = load_csv_grid(path, cfg)
        tables.extend(extract_grid(grid, str(path), path.stem, cfg))
    else:
        raise ValueError(f"unsupported file type: {path.suffix}")
    return tables


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_paths(paths: list, cfg: Optional[Config] = None, dedupe: bool = True) -> tuple[list[ExtractedTable], dict]:
    """Extract from files and/or folders. Returns (tables, report)."""
    exts = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(x for x in p.rglob("*") if x.suffix.lower() in exts and not x.name.startswith("~$"))
                     if p.is_dir() else [p])
    report = {"duplicate_files": [], "duplicate_tables": [], "errors": []}
    seen_files: dict[str, str] = {}
    seen_tables: dict[str, str] = {}
    tables: list[ExtractedTable] = []
    for f in files:
        sha = file_sha256(f)
        if sha in seen_files:
            report["duplicate_files"].append({"file": str(f), "same_as": seen_files[sha]})
            if dedupe:
                continue
        seen_files.setdefault(sha, str(f))
        try:
            ts = extract_file(f, cfg)
        except Exception as e:
            log.exception("failed on %s", f)
            report["errors"].append({"file": str(f), "error": str(e)})
            continue
        for t in ts:
            fp = t.fingerprint()
            if fp in seen_tables:
                report["duplicate_tables"].append({"table": t.table_id, "same_as": seen_tables[fp]})
                if dedupe:
                    continue
            seen_tables.setdefault(fp, t.table_id)
            tables.append(t)
    return tables, report


def save_tables(tables: list[ExtractedTable], out_dir: str | Path, long: bool = False, report: Optional[dict] = None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for t in tables:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", t.table_id).strip("_")
        t.df.to_csv(out / f"{slug}.csv", index=False)
        if long:
            t.to_long().to_csv(out / f"{slug}__long.csv", index=False)
        manifest.append(t.manifest())
    payload = {"tables": manifest, "report": report or {}}
    (out / "manifest.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


# =============================================================================
# Self-test (synthetic cases, no files needed)
# =============================================================================
def _selftest() -> None:
    cfg = Config()
    # 1) two stacked tables, multi-level header, blank-padded parent cells (CSV style), index row, footnote
    rows = [
        ["TABLE: X-1"], ["DEATHS BY PLACE (URBAN)"],
        ["SL. NO.", "DISTRICT", "INSTITUTIONAL", "", "", "DOMICILIARY", "", ""],
        ["", "", "MALE", "FEMALE", "TOTAL", "MALE", "FEMALE", "TOTAL"],
        ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)"],
        [1, "North", 10, 20, 30, 1, 2, 3],
        [2, "South", 5, 5, 10, 0, 1, 1],
        ["", "ALL", 15, 25, 40, 1, 3, 4],
        [], [],
        ["TABLE: X-1"], ["DEATHS BY PLACE (RURAL)"],
        ["SL. NO.", "DISTRICT", "INSTITUTIONAL", "", "", "DOMICILIARY", "", ""],
        ["", "", "MALE", "FEMALE", "TOTAL", "MALE", "FEMALE", "TOTAL"],
        [1, "North", 1, 1, 2, 0, 0, 0],
        [2, "South", 2, 2, 4, 1, 1, 2],
        ["", "ALL", 3, 3, 6, 1, 1, 2],
        ["* Note: provisional"],
    ]
    ts = extract_grid(grid_from_rows(rows), "t.csv", "t", cfg)
    assert len(ts) == 2, [t.summary() for t in ts]
    assert ts[0].columns[2] == "INSTITUTIONAL | MALE", ts[0].columns
    assert ts[0].columns[-1] == "DOMICILIARY | TOTAL", ts[0].columns
    assert list(ts[0].df["_row_kind"]) == ["data", "data", "total"]
    assert "URBAN" in ts[0].title and "RURAL" in ts[1].title
    assert ts[1].notes and ts[1].notes[0].startswith("* Note")

    # 2) two tables with NO blank row between them (different headers)
    rows = [["A", "B", "C"], [1, 2, 3], [4, 5, 6], ["X", "Y", "Z"], [7, 8, 9], [1, 1, 1]]
    ts = extract_grid(grid_from_rows(rows), "t.csv", "t2", cfg)
    assert len(ts) == 2 and ts[0].columns == ["A", "B", "C"] and ts[1].columns == ["X", "Y", "Z"], [t.columns for t in ts]

    # 3) all-text table + section rows + repeated header
    rows = [["Name", "Dept", "City"], ["Ann", "HR", "Pune"], ["Bob", "IT", "Delhi"],
            ["Name", "Dept", "City"], ["Cy", "IT", "Goa"]]
    ts = extract_grid(grid_from_rows(rows), "t.csv", "t3", cfg)
    assert len(ts) == 1 and len(ts[0].data_only()) == 3, ts[0].df

    # 4) section rows + subtotal reconciliation (section banners stay as rows)
    rows = [["Block", "Name", "Wet", "Dry"], ["NORTH"], [1, "a", 1, 2], [2, "b", 3, 4], ["", "North Total", 4, 6],
            ["SOUTH"], [1, "c", 5, 6], ["", "South Total", 5, 6]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t4", cfg)[0]
    assert list(t.df["_row_kind"]) == [
        "section", "data", "data", "subtotal", "section", "data", "subtotal"
    ], list(t.df["_row_kind"])
    assert list(t.df["_group"]) == [
        "NORTH", "NORTH", "NORTH", "NORTH", "SOUTH", "SOUTH", "SOUTH"
    ], list(t.df["_group"])
    # 2 sections + 3 data rows; subtotals dropped.
    assert len(t.data_only(include_sections=True)) == 5, len(t.data_only(include_sections=True))
    assert len(t.data_only()) == 3  # sections excluded by default
    print("selftest OK")


# =============================================================================
# CLI
# =============================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Layout-driven table extraction from Excel/CSV files")
    ap.add_argument("inputs", nargs="*", help="files and/or folders")
    ap.add_argument("-o", "--out", default="extracted", help="output folder")
    ap.add_argument("--long", action="store_true", help="also write tidy long-format CSVs")
    ap.add_argument("--keep-duplicates", action="store_true", help="do not drop duplicate files/tables")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.WARNING)
    if a.selftest:
        _selftest()
        return 0
    if not a.inputs:
        ap.error("give at least one file or folder (or --selftest)")
    tables, report = extract_paths(a.inputs, dedupe=not a.keep_duplicates)
    for t in tables:
        print(t.summary())
        for w in t.warnings:
            print("   !", w)
    save_tables(tables, a.out, long=a.long, report=report)
    print(f"\n{len(tables)} tables -> {a.out}/   duplicates: {len(report['duplicate_files'])} files, "
          f"{len(report['duplicate_tables'])} tables; errors: {len(report['errors'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())