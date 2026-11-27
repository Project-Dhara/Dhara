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

Data-safety guarantees
----------------------
* Values are never discarded: a value column becomes numeric only when EVERY non-blank value is numeric
  ('-' / 'NA' placeholders count as missing markers). Mixed columns keep their original values
  (t.column_types tells which is which; t.numeric(col) gives a coerced view on demand). Columns whose header
  looks like an identifier (code / id / pin / ...) are always kept as text (Config.identifier_column_patterns).
* t.raw_df holds the untouched cell values (blank stays blank; whitespace-only cells count as blank).
* Parent labels are filled down only inside their group: never across sections, repeated headers, confident
  totals or merged-cell boundaries. Filled cells are listed in the `_inferred` column.
* Total rows are scored from evidence (formula > label > reconciliation). Uncertain rows are kept as
  _row_kind == 'possible_total'; data_only() excludes them unless include_possible=True.

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
from decimal import ROUND_HALF_UP, Decimal
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

META_COLS = ("_row_kind", "_group", "_level", "_inferred", "_src_row")


# =============================================================================
# Configuration
# =============================================================================
@dataclass
class Config:
    wide_merge_frac: float = 0.8          # merge covering >= this share of block width => "wide"
    data_num_frac: float = 0.4            # numeric share of a row's cells to look like data
    note_prefixes: tuple = (
        "*", "†", "‡", "note", "source", "n.b", "nb:", "nb.", "footnote", "(*)", "# ",
        "नोट", "स्त्रोत", "स्रोत",  # Hindi Note / Source (chap10 DTC footnotes)
    )
    note_max_len: int = 90                # long single-cell text rows are treated as notes
    total_patterns: tuple = (
        r"\btotals?\b", r"^all$", r"^grand\b", r"\bsub[\s-]?totals?\b", r"^sum$", r"^overall$",
    )
    total_label_max_len: int = 40         # label-only total detection ignores long labels
    placeholders: tuple = ("-", "--", "---", "—", "–", "na", "n/a", "n.a.", "n.a", "nil", "..", "...")
    # columns whose header matches are identifiers: kept as text, never converted to numbers
    identifier_column_patterns: tuple = (r"\bcodes?\b", r"\bids?\b", r"\bpin\b", r"\bzip\b", r"\bphone\b", r"\bmobile\b")
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
    if _INDEX_STR.match(s) and s.startswith("("):      # "(1)" "(2)" are column-index labels, not negatives
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


class _FmtUnsupported(Exception):
    """Number format feature we do not render (conditions, scientific, elapsed time, ...)."""


_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _legacy_text(v: Any) -> str:
    """Plain text of a value as the extractor always produced it (integral floats without '.0')."""
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _split_excel_sections(fmt: str) -> list[str]:
    secs, cur, in_q, in_b = [], [], False, False
    for ch in fmt:
        if ch == '"' and not in_b:
            in_q = not in_q
        elif ch == "[" and not in_q:
            in_b = True
        elif ch == "]" and not in_q:
            in_b = False
        if ch == ";" and not in_q and not in_b:
            secs.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    secs.append("".join(cur))
    return secs


def _tokenize_excel_section(sec: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    i, n = 0, len(sec)
    while i < n:
        ch = sec[i]
        if ch == '"':
            j = sec.find('"', i + 1)
            j = n if j < 0 else j
            toks.append(("lit", sec[i + 1:j]))
            i = j + 1
        elif ch == "\\" and i + 1 < n:
            toks.append(("lit", sec[i + 1]))
            i += 2
        elif ch == "[":
            j = sec.find("]", i + 1)
            if j < 0:
                raise _FmtUnsupported
            body = sec[i + 1:j]
            i = j + 1
            if body.startswith("$"):                       # [$€-407] -> '€' ; [$-409] -> ''
                toks.append(("lit", body[1:].split("-", 1)[0]))
            elif re.match(r"^\s*[<>=]", body) or re.fullmatch(r"[hHmMsS]+", body):
                raise _FmtUnsupported                      # conditions / elapsed time
            # colours such as [Red] are not displayed
        elif ch == "_" and i + 1 < n:                      # _x: space the width of x
            toks.append(("lit", " "))
            i += 2
        elif ch == "*" and i + 1 < n:                      # *x: repeat-fill (no fixed width here)
            i += 2
        elif ch in "0#?":
            toks.append(("digit", ch))
            i += 1
        elif ch in ".,":
            toks.append(("sep", ch))
            i += 1
        elif ch == "%":
            toks.append(("pct", "%"))
            i += 1
        elif ch == "@":
            toks.append(("text", "@"))
            i += 1
        elif ch in "yYmMdDhHsS":
            toks.append(("date", ch.lower()))
            i += 1
        elif sec[i:i + 5].upper() == "AM/PM":
            toks.append(("ampm", sec[i:i + 5]))
            i += 5
        elif sec[i:i + 3].upper() == "A/P":
            toks.append(("ampm", sec[i:i + 3]))
            i += 3
        elif ch in "EeAaPp":
            raise _FmtUnsupported                          # scientific notation
        else:
            toks.append(("lit", ch))
            i += 1
    return toks


def _render_excel_date(d: Any, toks: list[tuple[str, str]]) -> str:
    h = getattr(d, "hour", 0)
    mi = getattr(d, "minute", 0)
    s = getattr(d, "second", 0)
    ampm = next((t[1] for t in toks if t[0] == "ampm"), None)
    if ampm is not None:                                   # 12-hour clock with AM/PM or A/P
        h12 = h % 12 or 12
        marker = ("PM" if h >= 12 else "AM") if ampm.upper() == "AM/PM" else ("P" if h >= 12 else "A")
        if ampm.islower():
            marker = marker.lower()
        h = h12
    date_letters = [t[1] for t in toks if t[0] == "date"]
    out: list[str] = []
    seen: list[str] = []                                   # date letters rendered so far
    i = 0
    while i < len(toks):
        kind, val = toks[i]
        if kind in ("lit", "sep"):                         # ',' '/' '-' ':' are literals in a date section
            out.append(val)
            i += 1
            continue
        if kind == "ampm":
            out.append(marker)
            i += 1
            continue
        if kind != "date":
            raise _FmtUnsupported                          # digit placeholders in a date section
        j = i
        while j < len(toks) and toks[j] == ("date", val):
            j += 1
        run = j - i
        # 'm' is minutes when it follows an hour token or precedes a seconds token
        prev_letter = seen[-1] if seen else None
        next_letter = next((t[1] for t in toks[j:] if t[0] == "date"), None)
        if val == "y":
            out.append(f"{d.year:04d}" if run >= 3 else f"{d.year % 100:02d}")
        elif val == "m" and (prev_letter == "h" or next_letter == "s"):
            out.append(f"{mi:02d}" if run >= 2 else str(mi))
        elif val == "m":
            if run == 1:
                out.append(str(d.month))
            elif run == 2:
                out.append(f"{d.month:02d}")
            elif run == 3:
                out.append(_MONTHS[d.month - 1][:3])
            else:
                out.append(_MONTHS[d.month - 1])
        elif val == "d":
            if run == 1:
                out.append(str(d.day))
            elif run == 2:
                out.append(f"{d.day:02d}")
            elif run == 3:
                out.append(_WEEKDAYS[d.weekday()][:3])
            else:
                out.append(_WEEKDAYS[d.weekday()])
        elif val == "h":
            out.append(f"{h:02d}" if run >= 2 else str(h))
        elif val == "s":
            out.append(f"{s:02d}" if run >= 2 else str(s))
        seen.append(val)
        i = j
    if not date_letters:
        raise _FmtUnsupported
    return "".join(out)


def _group_thousands(ip: str) -> str:
    return f"{int(ip):,}" if ip else ""


def _render_excel_number(v: Any, toks: list[tuple[str, str]], negative_section: bool) -> str:
    digit_pos = [i for i, t in enumerate(toks) if t[0] == "digit"]
    if not digit_pos:                                      # literal-only section, e.g. '"zero"' for zero values
        if any(t[0] in ("text", "date") for t in toks):
            raise _FmtUnsupported
        return "".join(t[1] for t in toks if t[0] in ("lit", "sep"))
    last_digit = digit_pos[-1]
    if any(t == ("sep", ",") for t in toks[last_digit + 1:]):
        raise _FmtUnsupported                              # trailing comma scales by 1000
    dot = next((i for i, t in enumerate(toks) if t == ("sep", ".")), None)
    int_digits = [toks[i][1] for i in digit_pos if dot is None or i < dot]
    dec_digits = [toks[i][1] for i in digit_pos if dot is not None and i > dot]
    thousands = any(t == ("sep", ",") for t in toks[:last_digit])
    pct = sum(1 for t in toks if t[0] == "pct")

    x = Decimal(str(abs(v))) * (Decimal(100) ** pct)
    ndec = len(dec_digits)
    q = x.quantize(Decimal(1).scaleb(-ndec), rounding=ROUND_HALF_UP) if ndec else x.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    s = format(q, "f")
    ip, _, fp = s.partition(".")
    nreq = dec_digits.count("0")
    while len(fp) > nreq and fp.endswith("0"):
        fp = fp[:-1]
    min_int = int_digits.count("0")
    ip = str(int(ip))
    if ip == "0" and min_int == 0:
        ip = ""
    ip = ip.rjust(min_int, "0")
    if thousands:
        ip = _group_thousands(ip)
    number = ip + (("." + fp) if (dot is not None and fp) else "")

    out: list[str] = []
    for i, (kind, val) in enumerate(toks):
        if kind == "digit":
            if i == digit_pos[0]:
                out.append(number)
        elif kind == "sep":
            if not (digit_pos[0] < i < last_digit):          # separators outside the number stay as literals
                out.append(val)
        elif kind == "pct":
            out.append("%")
        elif kind == "lit":
            out.append(val)
        else:                                                # @ or date letters in a numeric section
            raise _FmtUnsupported
    text = "".join(out)
    return ("-" + text) if (v < 0 and not negative_section) else text


def excel_display(v: Any, fmt: Optional[str]) -> Optional[str]:
    """The text Excel shows for a cell value under its number format, e.g. 1234.5 with '#,##0.00' -> '1,234.50',
    0.25 with '0%' -> '25%', a date with 'dd-mmm-yyyy' -> '01-Jul-2023'. Returns None when the format is not
    rendered here (the caller then keeps the value unchanged)."""
    if v is None or isinstance(v, (bool, str)):
        return None
    is_date = isinstance(v, (datetime, date))
    if not is_date and not isinstance(v, (int, float)):
        return None
    if not is_date and not math.isfinite(float(v)):
        return None
    if fmt is None or fmt.strip().lower() in ("", "general"):
        if is_date:
            return None
        if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return format(v, ".10g").replace("e", "E") if isinstance(v, float) else str(v)
    try:
        secs = _split_excel_sections(fmt)
        if is_date:
            sec = secs[0]
            return _render_excel_date(v, _tokenize_excel_section(sec)).strip()
        if len(secs) >= 3 and v == 0:
            sec, neg_sec = secs[2], False
        elif len(secs) >= 2 and v < 0:
            sec, neg_sec = secs[1], True
        else:
            sec, neg_sec = secs[0], False
        toks = _tokenize_excel_section(sec)
        if any(t[0] == "date" for t in toks):
            return None                                    # numeric value under a date format
        return _render_excel_number(v, toks, neg_sec).strip()
    except (_FmtUnsupported, ValueError, ArithmeticError, IndexError):
        return None


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
        # Display text per cell, only where it differs from the plain value (e.g. '1,234.50' for 1234.5).
        # Logic (totals, stubs, numeric checks) keeps using self.val; Preview output uses this text.
        self.shown: dict[tuple[int, int], str] = {}
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
        val: list[list[Any]] = []
        shown: dict[tuple[int, int], str] = {}
        for r_i, row in enumerate(ws_v.iter_rows()):
            line: list[Any] = []
            for c_i, cell in enumerate(row):
                v = cell.value
                if isinstance(v, (int, float, datetime, date)) and not isinstance(v, bool):
                    txt = excel_display(v, cell.number_format)     # what Excel shows for this cell
                    if txt is not None and txt != _legacy_text(v):
                        shown[(r_i, c_i)] = txt
                elif isinstance(v, str):
                    cv = clean_cell(v)
                    n = parse_number(cv) if isinstance(cv, str) else None
                    if n is not None and _legacy_text(n) != cv:    # text such as '$1,200' / '25%' as written
                        shown[(r_i, c_i)] = cv
                line.append(clean_cell(v))
            val.append(line)
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
        g = Grid(val, frm, merges, ws_f, ws_f.title)
        g.shown = shown
        out.append((ws_f.title, g, notes))
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
    shown: dict[tuple[int, int], str] = {}
    for r_i, row in enumerate(rows):
        out = []
        for c_i, v in enumerate(row):
            v = clean_cell(v)
            if isinstance(v, str):
                n = parse_number(v)
                if n is not None:
                    if _legacy_text(n) != v:                    # keep the text as written ('$1,200', '25%')
                        shown[(r_i, c_i)] = v
                    v = n
            out.append(v)
        val.append(out)
    val = _pad_grid(val)
    frm = [[None] * len(val[0]) for _ in val] if val else []
    val, frm = _trim(val, frm)
    g = Grid(val, frm, [], None, name)
    g.shown = shown
    return g


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


def _num_cols(inf: RowInfo, cfg: Config) -> set:
    return {c for c, v in inf.anchors if is_num(v) and not _is_ph(v, cfg)}


def _data_like_ctx(infos: dict, rest: list, i: int, cfg: Config) -> bool:
    """Rows with few numeric cells (e.g. two label columns + one value) count as data when the next row
    repeats the same numeric pattern and does not have more numeric cells (that would be a header row)."""
    inf = infos[rest[i]]
    if inf.is_index or inf.is_year or inf.n_num < 1 or inf.n_anchor < 2 or i + 1 >= len(rest):
        return False
    nxt = infos[rest[i + 1]]
    cols, ncols_ = _num_cols(inf, cfg), _num_cols(nxt, cfg)
    return bool(cols) and not nxt.is_index and cols <= ncols_ and len(cols) >= len(ncols_)


def _leading_serial(inf: RowInfo) -> Optional[int]:
    """Leading integral serial (1, 2, …) on a stub column — or None."""
    if not inf.anchors:
        return None
    _, v = min(inf.anchors, key=lambda a: a[0])
    if isinstance(v, str) and _INDEX_STR.match(v.strip()):
        return int(v.strip().strip("()"))
    if not isinstance(v, bool) and isinstance(v, (int, float)) and _is_integral(v):
        return int(v)
    return None


def _post_index_data_row(infos: dict, rest: list, i: int) -> bool:
    """After a column-index row, the next serial+label(+value) row is data even if the
    measure cell is non-numeric text (e.g. \"63.07 Lakhs\" on chap10 10.2(c) right)."""
    if i <= 0 or i >= len(rest):
        return False
    prev = infos[rest[i - 1]]
    if not prev.is_index:
        return False
    inf = infos[rest[i]]
    if inf.blank or inf.is_index or inf.is_year or inf.n_anchor < 2:
        return False
    serial = _leading_serial(inf)
    return serial is not None and serial >= 1


def _is_title_peel_row(inf: RowInfo, width: int) -> bool:
    """Leading caption row (single or bilingual dual-anchor, no numbers)."""
    if inf.blank or inf.n_num > 0 or inf.is_index or inf.is_year or width < 3:
        return False
    if inf.n_anchor == 1:
        return bool(inf.wide or inf.merge_w == 1 or inf.merge_w >= 2 or inf.merge_w / width >= 0.5)
    if inf.n_anchor == 2 and inf.n_text == 2 and inf.n_ph == 0:
        return True
    return False


def analyze(grid: Grid, r0: int, r1: int, c0: int, c1: int, cfg: Config, fallback: bool = False) -> Analysis:
    width = c1 - c0 + 1
    infos = {r: row_info(grid, r, c0, c1, cfg) for r in range(r0, r1 + 1)}
    an = Analysis(infos=infos)
    nz = [r for r in range(r0, r1 + 1) if not infos[r].blank]

    k = 0
    while k < len(nz):
        inf = infos[nz[k]]
        if _is_title_peel_row(inf, width):
            an.title_rows.append(nz[k])
            k += 1
        else:
            break
    rest = nz[k:]

    ds = next((
        r for i, r in enumerate(rest)
        if (
            _data_like(infos[r], width, cfg)
            or _data_like_ctx(infos, rest, i, cfg)
            or _post_index_data_row(infos, rest, i)
        )
    ), None)
    if ds is not None:
        pre = [r for r in rest if r < ds]
        an.index_rows = [r for r in pre if infos[r].is_index]
        an.header_rows = [r for r in pre if not infos[r].is_index]
        while len(an.header_rows) > 1 and infos[an.header_rows[-1]].n_anchor == 1 and infos[an.header_rows[-1]].n_num == 0:
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
            # Bilingual wrap under a data row (English labels after Hindi measures)
            # is not a new table header — skip when the previous non-blank row is data.
            if i > 0 and _data_like(infos[nz[i - 1]], width, cfg):
                continue
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


def _band_has_numeric_data(an: Analysis, a: int, b: int, c0: int, c1: int, cfg: Config) -> bool:
    width = c1 - c0 + 1
    for r in range(a, b + 1):
        inf = an.infos[r]
        if inf.blank:
            continue
        if _data_like(inf, width, cfg, loose=True) or inf.n_num >= 1:
            return True
    return False


def _is_continuation_band(prev: list, nxt: list, cfg: Config) -> bool:
    """True when nxt should be glued under prev (same table, blank-row gap)."""
    a, b, c0, c1, an = nxt
    pa, pb, pc0, pc1, pan = prev
    if pan.data_start is None or an.title_rows:
        return False
    if a - pb - 1 > 3:
        return False
    overlap = min(c1, pc1) - max(c0, pc0) + 1
    if overlap < 0.8 * max(c1 - c0 + 1, pc1 - pc0 + 1):
        return False
    # Strict: next band has data and no invented header/index/pre-section
    strict = (
        an.data_start is not None
        and not (an.header_rows or an.index_rows or an.pre_sections)
    )
    if strict:
        return True
    # Extended: prior is an established table; next has numeric/stub data even if
    # analyze() mis-labeled the first data row as header (placeholders / wrap rows).
    return bool(pan.header_rows) and _band_has_numeric_data(an, a, b, c0, c1, cfg)


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

    # 1b) a band with no title/header of its own, directly below a table with (nearly) the same columns,
    #     is a continuation of that table (blank separator rows inside long tables).
    #     Also glue trailing data bands when analyze() invents header_rows (e.g. chap10 10.(2a)
    #     NCR / Workshop / Depots after Accidents) — still reject clear new title banners.
    cont: list[list] = []
    for it in items:
        a, b, c0, c1, an = it
        if cont and _is_continuation_band(cont[-1], it, cfg):
            pa, pb, pc0, pc1, pan = cont[-1]
            cc0, cc1 = min(c0, pc0), max(c1, pc1)
            cont[-1] = [pa, b, cc0, cc1, analyze(grid, pa, b, cc0, cc1, cfg)]
            continue
        cont.append(it)
    items = cont

    # 2) split side-by-side tables FIRST (only if every part is a valid table).
    #    Doing this before embedded vertical splits keeps bilingual wrap rows
    #    from fragmenting each half of a dual-panel sheet (e.g. chap10 10.2(c)).
    side: list[list] = []
    for a, b, c0, c1, an in items:
        parts = _col_parts(grid, mask, a, b, c0, c1)
        if len(parts) >= 2:
            ans = [analyze(grid, a, b, p0, p1, cfg) for p0, p1 in parts]
            if all(x.data_start is not None for x in ans):
                lead = _lead_titles(grid, a, b, c0, c1)
                for (p0, p1), x in zip(parts, ans):
                    side.append([a, b, p0, p1, x, lead if not x.title_rows else []])
                continue
        side.append([a, b, c0, c1, an, []])

    # 3) split stacked tables with no blank row — per column band only
    split: list[list] = []
    stack = list(reversed(side))
    while stack:
        a, b, c0, c1, an, inherit = stack.pop()
        s = _embedded_split_start(an, cfg, c1 - c0 + 1)
        if s is not None and s > a:
            stack.append([s, b, c0, c1, analyze(grid, s, b, c0, c1, cfg), inherit])
            stack.append([a, s - 1, c0, c1, analyze(grid, a, s - 1, c0, c1, cfg), inherit])
        else:
            split.append([a, b, c0, c1, an, inherit])

    def _title_from_row(an: Analysis, r: int) -> str:
        parts = [clean_text(v) or "" for _, v in an.infos[r].anchors]
        return " / ".join(p for p in parts if p)

    # 4) turn items into table blocks / free-text (titles & notes)
    blocks: list[Block] = []
    pending: list[str] = []
    cur_band, band_pending = None, []
    for a, b, c0, c1, an, inherit in split:
        if an.data_start is None:
            text_rows = [r for r in range(a, b + 1) if not an.infos[r].blank]
            # Short all-text bands are captions for the next table — never fallback scrap.
            title_only = (
                bool(text_rows)
                and len(text_rows) <= 3
                and all(an.infos[r].n_num == 0 for r in text_rows)
            )
            if not title_only:
                an_fb = analyze(grid, a, b, c0, c1, cfg, fallback=True)
                multi = [r for r in an_fb.infos if an_fb.infos[r].n_anchor >= 2]
                if an_fb.data_start is not None and len(multi) >= 2:
                    an = an_fb
            if an.data_start is None:
                for r in range(a, b + 1):
                    t = " ".join(clean_text(v) or "" for _, v in an.infos[r].anchors).strip()
                    if t:
                        if blocks and looks_like_note(t, cfg):
                            blocks[-1].notes.append(t)
                        else:
                            pending.append(t)
                continue
        if cur_band != (a, b):                  # tables from the same row band (side by side) share pending titles
            cur_band, band_pending, pending = (a, b), pending, []
        titles = list(band_pending) + list(inherit)
        for r in an.title_rows:
            t = _title_from_row(an, r)
            if t:
                titles.append(t)
        blocks.append(Block(a, b, c0, c1, an, titles=titles))
    if pending and blocks:
        blocks[-1].notes.extend(pending)
    # Left panel full height, then right (stable reading order for side-by-side).
    blocks.sort(key=lambda blk: (blk.c0, blk.r0))
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
        if not anchors or any(is_num(v) for _, v in anchors):
            break
        if len(anchors) == 1:
            out.append(clean_text(anchors[0][1]) or "")
        elif len(anchors) == 2:
            joined = " / ".join(clean_text(v) or "" for _, v in anchors if clean_text(v))
            if joined:
                out.append(joined)
            else:
                break
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
    # "leaf" of a column = its lowest non-empty header cell (vertical merges can leave the last row blank)
    orig = [row[:] for row in H]
    eff = [next((orig[i][j] for i in range(len(H) - 1, -1, -1) if orig[i][j] is not None), None) for j in range(ncols)]
    below = [[any(orig[k][j] is not None for k in range(i + 1, len(H))) for j in range(ncols)] for i in range(len(H))]
    for i in range(len(H) - 1):                                  # fill upper levels to the right
        start = None
        for j in range(ncols):
            if H[i][j] is not None:
                start = j
                continue
            if start is None:
                continue
            if not below[i][j]:                                  # nothing under this column => not part of the group
                start = None
                continue
            if i == len(H) - 2 and eff[j] == eff[start]:         # bottom pair only: leaf pattern restarts => new group
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
            texts_ = {t.lower() for _, v in inf.anchors if (t := clean_text(v))}
            if inf.n_anchor >= 2 and texts_ and len(texts_ & htexts) / len(texts_) >= 0.8:
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
            elif i > 0 and _wrap_follows_data(kinds, infos, nz[i - 1], width, cfg):
                # Terminal label wrap under a data/section row (no following data)
                kinds[r] = ("section", text)
            else:
                kinds[r] = ("note", text)
        else:
            texts = {t.lower() for _, v in inf.anchors if (t := clean_text(v))}
            if texts and len(texts & htexts) / len(texts) >= 0.5:
                kinds[r] = ("header_repeat", None)
            elif nxt is not None and nxt.n_num >= 1:
                kinds[r] = ("section", text)
            elif i > 0 and _wrap_follows_data(kinds, infos, nz[i - 1], width, cfg):
                kinds[r] = ("section", text)
            else:
                kinds[r] = ("note", text)
    return kinds


def _wrap_follows_data(
    kinds: dict[int, tuple[str, Optional[str]]],
    infos: dict,
    prev_r: int,
    width: int,
    cfg: Config,
) -> bool:
    """True when prev body row was data/section (or looks like data) — keep wraps in Preview."""
    prev_kind = kinds.get(prev_r, (None,))[0]
    if prev_kind in ("data", "section"):
        return True
    prev = infos[prev_r]
    return _data_like(prev, width, cfg, loose=True) or prev.n_num >= 1


_AGG_RANGE = re.compile(r"\$?([A-Z]{1,3})\$?(\d+):\$?([A-Z]{1,3})\$?(\d+)")


def _formula_is_col_aggregate(f: Optional[str]) -> bool:
    if not f or not re.search(r"(SUM|SUBTOTAL|AGGREGATE)\s*\(", f, re.I):
        return False
    return any(m.group(1) == m.group(3) and int(m.group(4)) > int(m.group(2)) for m in _AGG_RANGE.finditer(f))


def _is_serial(vals: list[float]) -> bool:
    """Serial-number column: mostly +1 steps, with restarts back to 1 from a larger number allowed for grouped
    numbering. Count columns full of 0/1 values (or constants such as 0.000) are NOT serial numbers."""
    ints = [int(v) for v in vals if _is_integral(v)]
    if len(ints) < 2 or len(ints) / len(vals) < 0.8:
        return False
    steps = list(zip(ints, ints[1:]))
    inc = sum(1 for a, b in steps if b == a + 1)
    if inc == len(steps) and ints[0] == 1:               # a clean 1,2,3,... run (also 1,2)
        return True
    if len(ints) < 3:
        return False
    restart = sum(1 for a, b in steps if b == 1 and a > 1)
    return inc / len(steps) >= 0.4 and (inc + restart) / len(steps) >= 0.7


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
    return (ok / n if n else 1.0), n


_COL_ARITH = re.compile(r"^=\(?\$?([A-Z]{1,3})\$?\d+(?:[+\-]\$?\1\$?\d+){2,}\)?$")


def _formula_evidence(f: Optional[str]) -> Optional[str]:
    """'sum' = SUM/SUBTOTAL over a column range; 'arith' = =D5+D9+D13 style (same column, 3+ refs)."""
    if not f:
        return None
    if _formula_is_col_aggregate(f):
        return "sum"
    if _COL_ARITH.match(re.sub(r"\s+", "", f)):
        return "arith"
    return None


def detect_totals(grid: Grid, data_rows: list[int], stub_cols: list[int], num_cols: list[int],
                  leaf_col: Optional[int], can_reconcile: bool, cfg: Config):
    """Evidence-based total detection.

    Evidence weights:  formula over a column range = 3, same-column arithmetic formula = 2,
                       total-like label in the row's OWN (merge-aware, never forward-filled) label cells = 2,
                       numeric reconciliation with the rows above = 1 (supporting only).
    A row is a confident total/subtotal when it has formula or label evidence, score >= 2 and the numbers do not
    contradict it. Everything weaker (reconciliation only, label contradicted by the arithmetic, a blank-labelled
    row directly under a total) becomes 'possible_total'.
    Returns (kinds, warnings, evidence): kinds[row] in {'total','subtotal','possible_total'}.
    """
    nums = _num_rows(grid, data_rows, num_cols, cfg)
    pats = [re.compile(p, re.I) for p in cfg.total_patterns]
    warns: list[str] = []
    evidence: dict[int, str] = {}

    def own_label_hit(r: int) -> bool:
        for c in stub_cols:
            t = clean_text(_cell_value(grid, r, c))
            if t and len(t) <= cfg.total_label_max_len and any(p.search(t) for p in pats):
                return True
        return False

    def formula_ev(r: int) -> Optional[str]:
        evs = [_formula_evidence(grid.formula[r][c]) for c in num_cols if grid.formula[r][c]]
        if not evs:
            return None
        if sum(e == "sum" for e in evs) / len(evs) >= 0.5:
            return "sum"
        return "arith" if sum(e is not None for e in evs) / len(evs) >= 0.5 else None

    def leaf_key(r: int) -> Optional[str]:
        return clean_text(_cell_value(grid, r, leaf_col)) if leaf_col is not None else None

    def frac(r: int, scope: list[int]) -> float:
        return _reconcile(nums[r], [nums[x] for x in scope], cfg)[0]

    since_prev: list[int] = []        # ordinary rows since the previous confident total
    all_rows: list[int] = []          # all ordinary rows so far
    run: list[int] = []               # consecutive confident totals directly above
    conf: list[tuple[int, bool, bool, bool]] = []
    poss: dict[int, str] = {}
    direct: set[int] = set()          # rows flagged by label/formula evidence (may seed a continuation)
    for r in data_rows:
        lab, fm = own_label_hit(r), formula_ev(r)
        by_sum = False
        if not (lab or fm) and len(since_prev) >= 2 and len(nums[r]) >= 2:
            fr, n = _reconcile(nums[r], [nums[x] for x in since_prev], cfg)
            by_sum = n >= 2 and fr == 1.0
        if not (lab or fm or by_sum):
            since_prev.append(r)
            all_rows.append(r)
            run = []
            continue

        scopes: list[list[int]] = [sc for sc in (since_prev, all_rows, run if len(run) >= 2 else []) if sc]
        key = leaf_key(r)
        if key:                                           # M/F/O-style split: total of the same leaf label
            same = [x for x in all_rows if leaf_key(x) == key]
            if len(same) >= 2:
                scopes.append(same)
        matched = any(frac(r, sc) >= 0.8 for sc in scopes)
        attempted = bool(scopes)
        m_prev = bool(since_prev) and frac(r, since_prev) >= 0.8
        m_all = bool(all_rows) and frac(r, all_rows) >= 0.8

        score = {"sum": 3, "arith": 2}.get(fm, 0) + (2 if lab else 0) + (1 if matched else 0)
        contradicted = can_reconcile and attempted and not matched and fm != "sum" and bool(nums[r])
        parts = (["label"] if lab else []) + ([f"formula({fm})"] if fm else [])
        parts.append("reconciles" if matched else ("does-not-reconcile" if attempted and can_reconcile else "unverified"))
        if by_sum:
            parts.insert(0, "sum-of-rows-above")
        evidence[r] = "+".join(parts)

        if (lab or fm) and score >= 2 and not contradicted:
            conf.append((r, m_prev, m_all, bool(conf)))
            direct.add(r)
            if can_reconcile and attempted and not matched and nums[r]:
                warns.append(f"row {r + 1}: total formula found but the values do not reconcile with the rows above")
            since_prev = []
            run.append(r)
        else:
            poss[r] = evidence[r]
            if lab or fm:
                direct.add(r)
            if contradicted:
                warns.append(f"row {r + 1} looks like a total (label/formula) but does not reconcile; kept as 'possible_total'")

    # blank-labelled rows directly under a total block (e.g. M/F/O splits of a merged "Total") are uncertain
    left = [c for c in stub_cols if leaf_col is not None and c < leaf_col]
    if leaf_col is not None and left:
        done = {x[0] for x in conf} | set(poss)
        # only categorical split labels that recur across groups (MALE/FEMALE/OTHER) can continue a block;
        # a unique name such as a district is an ordinary row that merely lacks a serial number
        recurring: dict = {}
        for x in data_rows:
            if x not in done and leaf_key(x):
                recurring[leaf_key(x)] = recurring.get(leaf_key(x), 0) + 1
        for i, r in enumerate(data_rows):
            if i == 0 or r in done:
                continue
            prev = data_rows[i - 1]
            if prev == r - 1 and prev in direct and leaf_key(r) and recurring.get(leaf_key(r), 0) >= 2 \
                    and all(clean_text(_cell_value(grid, r, c)) is None for c in left):
                poss[r] = "continues-total-block(blank parent labels)"
                evidence[r] = poss[r]
                direct.add(r)
                done.add(r)

    kinds: dict[int, str] = {}
    flagged = {x[0] for x in conf} | set(poss)
    for r, m_prev, m_all, had_prior in conf:
        later_data = any(x > r and x not in flagged for x in data_rows)
        kinds[r] = "subtotal" if ((m_prev and not m_all and had_prior) or later_data) else "total"
    for r in poss:
        kinds[r] = "possible_total"
    return kinds, warns, evidence


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
    raw_df: Optional[pd.DataFrame] = None            # untouched cell values (blanks stay blank), same rows/columns as df
    column_types: dict = field(default_factory=dict)   # name -> numeric | text | mixed | identifier | empty
    total_evidence: dict = field(default_factory=dict) # source row -> {"kind":..., "evidence":...}

    @property
    def table_id(self) -> str:
        return f"{Path(self.source_file).stem}::{self.sheet}::{self.table_index}"

    def numeric(self, column: str) -> pd.Series:
        """Coerced numeric view of a column (non-numeric -> NaN). Original values stay in .df / .raw_df."""
        return pd.to_numeric(self.df[column].map(parse_number), errors="coerce")

    def data_only(self, include_totals: bool = False, keep_meta: bool = False,
                  include_possible: bool = False, include_sections: bool = False,
                  include_index: bool = False) -> pd.DataFrame:
        """Ordinary data rows. Totals/subtotals are excluded unless include_totals; uncertain rows
        ('possible_total') are excluded unless include_possible (or include_totals).

        ``include_sections`` / ``include_index`` are for Dhara ingest/Preview compatibility;
        section banners and column-number index rows (1,2,3…) are kept when present.
        """
        d = self.df
        keep = ["data"]
        if include_totals:
            keep += ["total", "subtotal", "possible_total"]
        elif include_possible:
            keep.append("possible_total")
        if include_sections:
            keep.append("section")
        if include_index:
            keep.append("index")
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

    def to_long(self, include_totals: bool = False, dropna: bool = True, include_possible: bool = False) -> pd.DataFrame:
        d = self.data_only(include_totals=include_totals, keep_meta=True, include_possible=include_possible)
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
            "n_total_rows": int(self.df["_row_kind"].isin(["total", "subtotal"]).sum()),
            "n_possible_total_rows": int((self.df["_row_kind"] == "possible_total").sum()),
            "column_types": self.column_types,
            "total_evidence": {str(k): v for k, v in self.total_evidence.items()},
            "confidence": round(self.confidence, 3), "warnings": self.warnings,
            "fingerprint": self.fingerprint(),
        }


# =============================================================================
# Table construction
# =============================================================================
def _ref(r0: int, c0: int, r1: int, c1: int) -> str:
    return f"{get_column_letter(c0 + 1)}{r0 + 1}:{get_column_letter(c1 + 1)}{r1 + 1}"


def _cell_value(grid: Grid, r: int, c: int, numeric_merges: bool = False) -> Any:
    """Cell value with merged ranges expanded. Text merges always expand; numeric merges only when asked
    (label/serial columns), so merged numbers in value columns are not duplicated."""
    v = grid.val[r][c]
    if v is None and (r, c) in grid.merge_at:
        mr0, mc0, _, _ = grid.merge_at[(r, c)]
        a = grid.val[mr0][mc0]
        if a is not None and (numeric_merges or not is_num(a)):
            return a
    return v


def _shown_cell(grid: Grid, r: int, c: int, numeric_merges: bool = False) -> Any:
    """Display text of the cell that _cell_value() returns (same merge rules). None when the cell is blank
    or when its text is the plain value (then the value itself is shown)."""
    v = _cell_value(grid, r, c, numeric_merges)
    if v is None:
        return None
    src = (r, c)
    if grid.val[r][c] is None and (r, c) in grid.merge_at:
        src = grid.merge_at[(r, c)][:2]
    return grid.shown.get(src, v)


def _finalize_column(values: list, is_stub: bool, is_identifier: bool, cfg: Config, name: str, warns: list,
                     shown: Optional[list] = None):
    """Return (Series, column_type).  column_type: numeric | text | mixed | identifier | empty.

    Nothing is discarded: a value column becomes numeric only if EVERY non-blank value is numeric
    (placeholders such as '-' / 'NA' are treated as missing markers). Otherwise the original values are
    kept untouched. The untouched cell values are also always available in ExtractedTable.raw_df.

    ``shown`` (optional, aligned with ``values``) is the display text of cells written with a number format
    or as text in the file ('1,234.50', '25%', '$1,200', '01-Jul-2023'). Type decisions use ``values``; when the
    column has any such cell, the output shows the display text for every cell, exactly as in the sheet/file."""
    shown = list(shown) if shown is not None else [None] * len(values)
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
    original = pd.Series(list(values), dtype="object")
    if n_d + n_t == 0:
        return original, "empty"                         # all blank / placeholders: keep as they are

    def _needs_display(v: Any, s: Any) -> bool:
        """True when the display text differs from the plain output this cell would otherwise get."""
        if not isinstance(s, str) or v is None:
            return False
        base = parse_number(v) if isinstance(v, str) else v
        return base is not None and s != _legacy_text(base)

    display_mode = any(_needs_display(v, s) for v, s in zip(values, shown))
    disp = [None if v is None else (s if isinstance(s, str) else _legacy_text(v)) for v, s in zip(values, shown)]
    display_series = pd.Series(disp, dtype="object")

    if is_identifier:                                    # codes / ids: always text, never numeric
        return pd.Series([None if k == "n" else d for d, k in zip(disp, kinds)], dtype="object"), "identifier"
    if n_t == 0 and display_mode:                        # numeric column written with formats: show as written
        return pd.Series([None if k == "n" else d for d, k in zip(disp, kinds)], dtype="object"), "numeric"
    if n_t == 0:                                         # confidently numeric
        nums = [None if k in "np" else parse_number(v) for v, k in zip(values, kinds)]
        # Use object + None (not pandas Int64/NA): Dhara persists table rows as
        # JSONB and downstream stamp/confidence code treats blanks as None.
        if all(x is None or _is_integral(x) for x in nums):
            return pd.Series([None if x is None else int(x) for x in nums], dtype="object"), "numeric"
        return pd.Series(
            [None if x is None else float(x) for x in nums], dtype="object"
        ), "numeric"
    if is_stub:                                          # label column with some numbers: normalise to text
        return pd.Series([None if k == "n" else d for d, k in zip(disp, kinds)], dtype="object"), "text"
    if n_d / (n_d + n_t) >= 0.5:
        warns.append(f"column '{name}': mixed values ({n_d} numeric, {n_t} text); original values kept "
                     f"(use .numeric('{name}') for a coerced view)")
        return (display_series if display_mode else original), "mixed"
    return (display_series if display_mode else original), "text"


_ROMAN = re.compile(r"^[IVXLCDM]+$")


def _row_levels(grid: Grid, rows: list, stub: list[int], leaf: Optional[int], cfg: Config) -> Optional[list]:
    """Hierarchy hint for xlsx: rank of (roman numbering, bold, indent) of the row label.
    Only emitted when the table really uses more than one style signature."""
    if grid.ws is None or not stub:
        return None
    label_col = leaf if leaf is not None else stub[0]
    keys: list[Optional[tuple]] = []
    for r, kind in rows:
        if kind != "data":
            keys.append(None)
            continue
        sv = clean_text(_cell_value(grid, r, stub[0]))
        rr, cc = r, label_col
        if (r, label_col) in grid.merge_at:
            rr, cc = grid.merge_at[(r, label_col)][:2]
        st = grid.style(rr, cc)
        keys.append((0 if (sv and _ROMAN.match(sv)) else 1, 0 if st.get("bold") else 1, st.get("indent", 0)))
    uniq = sorted({k for k in keys if k is not None})
    if len(uniq) < 2:
        return None
    rank = {k: i for i, k in enumerate(uniq)}
    return [None if k is None else rank[k] for k in keys]


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

    def fill_ratio(rows, c):
        return sum(1 for r in rows if _cell_value(grid, r, c, numeric_merges=True) is not None) / max(1, len(rows))
    # leaf label = right-most stub column that is complete; stub columns left of it with gaps are parents
    leaf0 = next((c for c in reversed(stub) if fill_ratio(data_rows, c) >= 0.98), None)
    hierarchical = leaf0 is not None and any(c < leaf0 and fill_ratio(data_rows, c) < 1.0 for c in stub)
    # parent rows aggregate their children in hierarchical tables, so totals can't be reconciled generically there
    tot, tw, evidence = detect_totals(grid, data_rows, stub, num_cols, leaf0, not hierarchical, cfg)
    warns.extend(tw)
    conf -= min(0.3, 0.05 * len(tw))
    plain = [r for r in data_rows if r not in tot]
    leaf = next((c for c in reversed(stub) if fill_ratio(plain, c) >= 0.98), None)
    parents = [c for c in stub if leaf is not None and c < leaf and fill_ratio(plain, c) < 1.0]

    sections: list[str] = []
    group_for: dict[int, str] = {}
    prev_kind = None
    ordered = sorted(kinds)
    rows_out = []                                   # (row, kind, group, record, inferred_column_names)
    # Index before wrap/pre_sections so Preview matches Excel: header → index → banners → data.
    for r in list(an.index_rows):
        rec = {c: _cell_value(grid, r, c, numeric_merges=(c in stub)) for c in cols}
        rows_out.append((r, "index", " > ".join(sections) if sections else None, rec, []))
        prev_kind = "index"
    # Keep peeled pre-data banners visible for Preview (same as mid-table sections).
    for r in list(an.pre_sections):
        t = clean_text(" ".join(clean_text(v) or "" for _, v in an.infos[r].anchors))
        if not t:
            continue
        sections = sections + [t] if prev_kind == "section" else [t]
        prev_kind = "section"
        rec = {c: _cell_value(grid, r, c, numeric_merges=(c in stub)) for c in cols}
        rows_out.append((r, "section", " > ".join(sections), rec, []))
    carry: dict[int, tuple] = {}                    # parent col -> (value, last row of its merged range or None)
    for r in ordered:
        k, label = kinds[r]
        if k == "section":
            sections = sections + [label] if prev_kind == "section" else [label]
            prev_kind = "section"
            carry.clear()                           # a new section never inherits labels from the previous one
            # Keep mid-table banners (e.g. North / South / "B | Percentage") as visible rows.
            rec = {c: _cell_value(grid, r, c, numeric_merges=(c in stub)) for c in cols}
            rows_out.append((r, "section", " > ".join(sections), rec, []))
            continue
        prev_kind = k
        if k == "note":
            notes.append(label)
            continue
        if k == "header_repeat":
            carry.clear()
            continue
        if k != "data":
            continue
        rec = {c: _cell_value(grid, r, c, numeric_merges=(c in stub)) for c in cols}
        kind = tot.get(r, "data")
        filled: list[str] = []
        if kind == "data":
            for pi, c in enumerate(parents):
                if rec[c] is None:
                    cand = carry.get(c)
                    if cand is not None and (cand[1] is None or r <= cand[1]):   # never cross a merged-cell boundary
                        rec[c] = cand[0]
                        filled.append(names[cols.index(c)])
                else:
                    prev = carry.get(c)
                    if prev is None or prev[0] != rec[c]:
                        for c2 in parents[pi + 1:]:                              # new parent => deeper labels are stale
                            carry.pop(c2, None)
                    m = grid.merge_at.get((r, c))
                    carry[c] = (rec[c], m[2] if m else None)
        elif kind in ("total", "subtotal"):
            carry.clear()                           # labels never carry across a confident total row
        rows_out.append((r, kind, " > ".join(sections), rec, filled))

    # Display text per output cell (as written in the sheet/file). Inferred (filled-down) labels have no
    # display text of their own, so they keep their value.
    shown_rows = []
    for r, _k, _g, _rec, filled in rows_out:
        fs = set(filled)
        shown_rows.append([None if names[i] in fs else _shown_cell(grid, r, c, numeric_merges=(c in stub))
                           for i, c in enumerate(cols)])
    ident = [any(re.search(p, n, re.I) for p in cfg.identifier_column_patterns) for n in names]
    series, ctypes = {}, {}
    for i, ((c, name), is_id) in enumerate(zip(zip(cols, names), ident)):
        series[name], ctypes[name] = _finalize_column([rec[c] for _, _, _, rec, _ in rows_out], c in stub, is_id,
                                                      cfg, name, warns,
                                                      shown=[sr[i] for sr in shown_rows])
    df = pd.DataFrame(series)
    raw = pd.DataFrame({name: pd.Series([grid.val[r][c] for r, *_ in rows_out], dtype="object")
                        for c, name in zip(cols, names)})
    df["_row_kind"] = [k for _, k, _, _, _ in rows_out]
    df["_group"] = [g or None for _, _, g, _, _ in rows_out]
    levels = _row_levels(grid, [(r, k) for r, k, _, _, _ in rows_out], stub, leaf, cfg)
    if levels is not None:
        df["_level"] = pd.Series(levels, dtype="object")
    if any(f for *_, f in rows_out):
        df["_inferred"] = [", ".join(f) if f else None for *_, f in rows_out]
    df["_src_row"] = [r + 1 for r, *_ in rows_out]
    raw["_src_row"] = df["_src_row"]
    n_poss = sum(1 for _, k, *_ in rows_out if k == "possible_total")
    if n_poss:
        warns.append(f"{n_poss} row(s) classified 'possible_total' (uncertain); review them. They are excluded from "
                     f"data_only() unless include_possible=True")
        conf -= min(0.2, 0.03 * n_poss)

    # drop columns that are entirely empty and have no header
    drop = [n for c, n, p in zip(cols, names, paths) if not p and df[n].isna().all()]
    if drop:
        keep_idx = [i for i, n in enumerate(names) if n not in drop]
        df = df.drop(columns=drop)
        raw = raw.drop(columns=drop)
        ctypes = {k: v for k, v in ctypes.items() if k not in drop}
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
        fr = [grid.formula[r][c] is not None for r, k, *_ in rows_out if k == "data"]
        if fr and sum(fr) / len(fr) >= 0.8:
            derived.append(n)

    title = " - ".join(dict.fromkeys(blk.titles))
    hdr_range = _ref(an.header_rows[0], c0, an.header_rows[-1], c1) if an.header_rows else None
    return ExtractedTable(
        source_file=source, sheet=sheet, table_index=idx, title=title, notes=notes,
        cell_range=_ref(blk.r0, c0, blk.r1, c1), header_range=hdr_range,
        header_paths=paths, columns=names, col_letters=[get_column_letter(c + 1) for c in cols],
        stub_columns=[names[cols.index(c)] for c in stub], derived_columns=derived,
        df=df, warnings=warns, confidence=max(0.0, conf), raw_df=raw, column_types=ctypes,
        total_evidence={r + 1: {"kind": tot[r], "evidence": evidence.get(r, "")} for r in tot},
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
    assert list(ts[0].df["_row_kind"]) == ["index", "data", "data", "total"], list(ts[0].df["_row_kind"])
    assert len(ts[0].data_only()) == 2
    assert len(ts[0].data_only(include_index=True)) == 3
    assert "URBAN" in ts[0].title and "RURAL" in ts[1].title
    assert ts[1].notes and ts[1].notes[0].startswith("* Note")

    # 2) two tables with NO blank row between them (different headers)
    rows = [["A", "B", "C"], [1, 2, 3], [4, 5, 6], ["X", "Y", "Z"], [7, 8, 9], [1, 1, 1]]
    ts = extract_grid(grid_from_rows(rows), "t.csv", "t2", cfg)
    assert len(ts) == 2 and ts[0].columns == ["A", "B", "C"] and ts[1].columns == ["X", "Y", "Z"], [t.columns for t in ts]
    # [1,2,3] is a column-index row under the first header — kept for Preview, not as data
    assert "index" in list(ts[0].df["_row_kind"]) and list(ts[0].df["_row_kind"]).count("data") == 1

    # 3) all-text table + section rows + repeated header
    rows = [["Name", "Dept", "City"], ["Ann", "HR", "Pune"], ["Bob", "IT", "Delhi"],
            ["Name", "Dept", "City"], ["Cy", "IT", "Goa"]]
    ts = extract_grid(grid_from_rows(rows), "t.csv", "t3", cfg)
    assert len(ts) == 1 and len(ts[0].data_only()) == 3, ts[0].df

    # 4) section rows + subtotal reconciliation (section banners stay visible for Preview)
    rows = [["Block", "Name", "Wet", "Dry"], ["NORTH"], [1, "a", 1, 2], [2, "b", 3, 4], ["", "North Total", 4, 6],
            ["SOUTH"], [1, "c", 5, 6], ["", "South Total", 5, 6]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t4", cfg)[0]
    assert list(t.df["_row_kind"]) == [
        "section", "data", "data", "subtotal", "section", "data", "subtotal"
    ], list(t.df["_row_kind"])
    assert list(t.df["_group"]) == [
        "NORTH", "NORTH", "NORTH", "NORTH", "SOUTH", "SOUTH", "SOUTH"
    ]
    assert len(t.data_only()) == 3  # data only by default excludes sections/totals
    assert len(t.data_only(include_sections=True)) == 5
    assert len(t.data_only(include_totals=True, include_sections=True)) == 7
    # 5) minority text is never destroyed; identifiers stay text; raw_df keeps the originals
    codes = ["41", "17", "93", "25", "62", "8", "77", "41", "17", "93", "25", "62", "8", "77", "41", "17", "93", "25", "X", "99-B"]
    rows = [["Case ID", "Grade", "Count"]] + [[f"c{i}", codes[i], i + 1] for i in range(20)]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t5", cfg)[0]
    assert list(t.df["Grade"])[-2:] == ["X", "99-B"] and t.column_types["Grade"] == "mixed", t.column_types
    assert t.column_types["Case ID"] == "identifier" and t.column_types["Count"] == "numeric"
    assert t.numeric("Grade").isna().sum() == 2 and list(t.raw_df["Grade"])[-2:] == ["X", "99-B"]

    # 6) parent labels: no carry across a section start, inferred cells are reported, raw blanks are preserved
    rows = [["Block", "Name", "Sex", "Val"], ["NORTH"], [1, "alpha", "M", 5], ["", "", "F", 6],
            ["SOUTH"], ["", "", "M", 7], [2, "beta", "M", 9], ["", "", "F", 1]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t6", cfg)[0]
    # indices: 0 NORTH section, 1 alpha M, 2 F, 3 SOUTH section, 4 M under SOUTH, 5 beta M, 6 F
    assert list(t.df["_row_kind"])[:4] == ["section", "data", "data", "section"], list(t.df["_row_kind"])
    assert pd.isna(t.df["Block"].iloc[4]) and pd.isna(t.df["Name"].iloc[4])           # SOUTH's first data row stays blank
    assert t.df["_inferred"].iloc[2] == "Block, Name" and pd.isna(t.df["_inferred"].iloc[4])
    assert list(t.raw_df["Block"])[2] is None and list(t.raw_df["Block"])[5] == 2

    # 7) a Total row must not contaminate the next row; contradicted labels / formula evidence
    rows = [["Region", "Item", "Sales"], ["N", "a", 10], ["N", "b", 20], ["Total", None, 30], ["S", None, 15], ["S", "c", 15]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t7", cfg)[0]
    assert list(t.df["_row_kind"]) == ["data", "data", "subtotal", "data", "data"], list(t.df["_row_kind"])
    rows = [["Name", "Dept", "Amt"], ["a", "x", 10], ["b", "x", 20], ["Total Knee Replacement", "x", 999], ["c", "y", 5]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t7b", cfg)[0]
    assert t.df["_row_kind"].iloc[2] == "possible_total" and len(t.data_only()) == 3
    assert len(t.data_only(include_possible=True)) == 4
    val = [["Item", "Q1", "Q2"], ["a", 1, 2], ["b", 3, 4], ["Total", 99, 99]]
    frm = [[None] * 3, [None] * 3, [None] * 3, [None, "=SUM(B2:B3)", "=SUM(C2:C3)"]]
    t = extract_grid(Grid(val, frm, [], None, "g"), "g.xlsx", "g", cfg)[0]
    assert t.df["_row_kind"].iloc[2] == "total" and any("do not reconcile" in w for w in t.warnings)

    # 8) blank-labelled rows under a total: categorical split labels are uncertain, unique names are ordinary rows
    rows = [["No", "Occ", "Sex", "Val"], [1, "Prof", "M", 5], ["", "", "F", 6], [2, "Admin", "M", 7], ["", "", "F", 8],
            ["", "TOTAL", "M", 12], ["", "", "F", 14]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t8", cfg)[0]
    ks = list(t.df["_row_kind"])
    assert ks[:4] == ["data"] * 4 and ks[4] in ("total", "subtotal") and ks[5] == "possible_total", ks
    rows = [["No", "Name", "V"], [1, "A", 5], [2, "B", 6], ["", "TOTAL", 11], ["", "C", 7]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t8b", cfg)[0]
    assert list(t.df["_row_kind"]) == ["data", "data", "subtotal", "data"], list(t.df["_row_kind"])

    # 9) label-heavy rows (2 text columns + 1 value) are data, and 0/1 count columns are not serial numbers
    rows = [["Name", "Flag", "N"], ["a", 0, 3], ["b", 1, 4], ["c", 0, 5], ["d", 1, 6], ["e", 1, 7]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t9", cfg)[0]
    assert t.stub_columns == ["Name"] and len(t.data_only()) == 5, (t.stub_columns, len(t.data_only()))

    # 10) display text: values are shown as written (symbols, separators, percent, dates); logic stays numeric
    assert excel_display(1234.5, "#,##0.00") == "1,234.50" and excel_display(0.25, "0%") == "25%"
    assert excel_display(-1234.5, '"$"#,##0.00') == "-$1,234.50" and excel_display(1.5, "0.00E+00") is None
    assert excel_display(datetime(2023, 7, 1), "dd-mmm-yyyy") == "01-Jul-2023"
    rows = [["Item", "Price", "Pct"], ["a", "$1,200", "25%"], ["b", "$300.50", "12.5%"], ["Total", "$1,500.50", "37.5%"]]
    t = extract_grid(grid_from_rows(rows), "t.csv", "t10", cfg)[0]
    assert list(t.df["Price"]) == ["$1,200", "$300.50", "$1,500.50"], list(t.df["Price"])
    assert list(t.df["_row_kind"]) == ["data", "data", "total"] and t.numeric("Price").iloc[2] == 1500.5
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
