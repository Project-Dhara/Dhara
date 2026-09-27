"""
Multi-row / merged (colspan + rowspan) header resolution for pymupdf tables.

Works for any table with the common government/statistical layout:
  - a text parent row with spanning group labels (units, dimensions, …)
  - an optional leaf row of short codes under those spans (1, 2, Male, …)
  - row-label columns that span both header rows (Year, S.No., Total, …)

Domain-agnostic: decisions use cell shape (length, magnitude, emptiness),
not vocabulary like "birth order" or "not stated".

pymupdf `Table.extract()` puts spanning text in the top-left cell and leaves
other span cells empty. Blindly using `rows[0]` as columns invents phantom
columns and spills leaf headers into the first data row.
"""

from __future__ import annotations

import math
import re
from typing import Any, List, Optional, Sequence, Tuple

# Short stub names that usually rowspan the full header block (not group+leaf).
# Do NOT include Year/Years — those are commonly colspan parents over 2019, 2020, …
_ROWSPAN_STUBS = {
    "SL", "SL.", "S.NO", "S.NO.", "S NO", "S. NO.", "SL. NO.", "SL.NO.",
    "STATE", "STATES", "STATES/UTS", "STATES / UTS",
    "UT", "UTS", "INDICATOR", "INDICATORS", "NAME", "TOTAL", "ALL",
}

_COL_NUM_RE = re.compile(r"^\(\d+\)$")
# Bare 1..N index strip under headers (no parentheses), common in CRS/statistical PDFs.
_BARE_INDEX_RE = re.compile(r"^\d{1,2}$")


def _row_is_column_number_strip(row: Sequence[Any], n_cols: int) -> bool:
    """True for '(1)(2)(3)' or bare 1..N reference strips under headers."""
    non_empty = [v for v in row if _cell_str(v)]
    if len(non_empty) < 2:
        return False
    paren_hits = sum(1 for v in non_empty if _COL_NUM_RE.match(_cell_str(v)))
    if paren_hits > len(non_empty) * 0.5:
        return True
    if len(non_empty) < max(3, int(n_cols * 0.6)):
        return False
    if not all(_BARE_INDEX_RE.match(_cell_str(v)) for v in non_empty):
        return False
    try:
        nums = [int(_cell_str(v)) for v in non_empty]
    except ValueError:
        return False
    return bool(nums) and nums == list(range(1, len(nums) + 1))


# Comparator / open-ended codes: >8, <5, 65+, >=10 (still short header leaves).
_OPEN_CODE_RE = re.compile(r"^[<>]=?\s*\d+\+?$|^\d+\+$")
# Unit banners that often colspan measure columns.
_UNIT_GROUP_RE = re.compile(
    r"^(?:in\s+)?(?:lakhs?|thousands?|crores?|millions?|%|percent(?:age)?)$",
    re.IGNORECASE,
)
# Full-width caption inside the grid (must not become header_group).
_TABLE_BANNER_RE = re.compile(
    r"^(?:table\s*[:.\-–—]?\s*[a-z0-9][\w\s.\-–—/]*|"
    r"statement\s*[:.\-–—]?\s*\d+|"
    r"annex(?:ure)?\s*[:.\-–—]?\s*[a-z0-9]+)$",
    re.IGNORECASE,
)
# Document-kind + short id only (e.g. "TABLE: B-6", "TABLE- B-1"), not the
# descriptive title that often follows on the next full-width row.
_DOC_KIND_RE = (
    r"(?:TABLE|TAB\.?|STATEMENT|ANNEX(?:URE)?|SCHEDULE|EXHIBIT|APPENDIX)"
)
_TABLE_ID_TOKEN_RE = r"[A-Z0-9][\w.\-–—/]*"
_TABLE_ID_ONLY_RE = re.compile(
    rf"^{_DOC_KIND_RE}\s*[:.\-–—]?\s*{_TABLE_ID_TOKEN_RE}"
    rf"(?:\s*\([^)]{{0,48}}\))?\s*$",
    re.IGNORECASE,
)
# Id and descriptive title jammed into one full-width cell.
_TABLE_ID_THEN_TITLE_RE = re.compile(
    rf"^(?P<id>{_DOC_KIND_RE}\s*[:.\-–—]?\s*{_TABLE_ID_TOKEN_RE}"
    rf"(?:\s*\([^)]{{0,48}}\))?)"
    rf"(?:\s*[:.\-–—]\s*|\s+)(?P<title>\S.+)$",
    re.IGNORECASE,
)

# Leaf header cells are short; long occupation / description strings are data.
_LEAF_MAX_LEN = 24
# Integers at or above this look like measurements/counts, not category codes.
_MEASUREMENT_ABS_MIN = 100


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s)
    if s.lower() in {"nan", "none", "<na>"}:
        return ""
    return s


def _normalize_numeric_token(v: Any) -> str:
    """Strip footnotes/wrappers so '(10.6)' and '*(45.18)' parse as numbers."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and math.isnan(v):
            return ""
        return str(v)
    s = _cell_str(v).replace(",", "").replace("%", "").replace("*", "").strip()
    # Parenthetical percentages / shares in statistical PDFs.
    if len(s) >= 3 and s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    return s


def _is_numeric_cell(v: Any) -> bool:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and math.isnan(v):
            return False
        return True
    s = _normalize_numeric_token(v)
    if not s or s in {"-", "—", "–", "Null", "null", "NA", "N/A"}:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _numeric_abs(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return abs(float(v))
    s = _normalize_numeric_token(v)
    if not s:
        return None
    try:
        return abs(float(s))
    except ValueError:
        return None


def _is_year_code(v: Any) -> bool:
    """Four-digit calendar years used as leaf column labels (2001, 2011, …)."""
    s = _cell_str(v).replace(",", "").strip()
    if not re.fullmatch(r"\d{4}", s):
        return False
    n = _numeric_abs(v)
    return n is not None and 1800 <= n <= 2100


def _is_measurement_number(v: Any) -> bool:
    """Large counts / values that belong in data rows, not leaf header codes."""
    if _is_year_code(v):
        return False
    n = _numeric_abs(v)
    if n is None:
        return False
    if n >= _MEASUREMENT_ABS_MIN:
        return True
    # Multi-decimal measurements (150.54) and parenthetical shares (10.6) are data;
    # plain small ints remain codes.
    s = _normalize_numeric_token(v)
    if re.fullmatch(r"\d+\.\d+", s) and n >= 1:
        return True
    return False


def _is_leaf_header_token(v: Any) -> bool:
    """
    Short token suitable as a leaf column label under a spanning parent.

    Examples that match structurally: 1, 2, >8, Male, Rural, Q1, 2001, 15-19.
    Examples that do not: 0 / blank counts, 1954 as a count, 150.54, long prose.
    """
    s = _cell_str(v)
    if not s or len(s) > _LEAF_MAX_LEN:
        return False
    if _is_year_code(v):
        return True
    if _is_measurement_number(v):
        return False
    if _OPEN_CODE_RE.match(s.replace(" ", "")):
        return True
    if _is_numeric_cell(v):
        n = _numeric_abs(v)
        # Zero is almost never a column code; it is a count that leaks into headers.
        if n is None or n == 0:
            return False
        return n < _MEASUREMENT_ABS_MIN
    # Short text / hyphenated codes (Rural, 15-19, Not stated, …)
    return True


def _is_rowspan_stub(text: str) -> bool:
    u = (text or "").upper().strip()
    if not u:
        return False
    if u in _ROWSPAN_STUBS:
        return True
    if u.startswith("SL") or u.startswith("S.NO") or u.startswith("S. NO"):
        return True
    if u in {"TOTAL", "ALL"}:
        return True
    return False


def _pad_row(row: Sequence[Any], n_cols: int) -> List[Any]:
    cells = list(row)
    if len(cells) < n_cols:
        cells.extend([None] * (n_cols - len(cells)))
    return cells[:n_cols]


def _blank(row: Sequence[Any]) -> bool:
    return not any(_cell_str(v) for v in row)


def _row_is_full_width_banner(row: Sequence[Any]) -> bool:
    """
    Caption / title row that colspans the entire table (e.g. "TABLE: B-10").

    These must be skipped: horizontal fill would copy the caption into every
    column and surface it as a fake parent header_group in Preview.
    """
    cells = list(row)
    if len(cells) < 2:
        return False
    non_empty = [_cell_str(v) for v in cells if _cell_str(v)]
    if not non_empty:
        return False
    unique = {s.upper() for s in non_empty}
    if len(unique) != 1:
        return False
    label = non_empty[0].strip()
    # Classic extract: one non-empty cell, rest empty under a full colspan.
    if len(non_empty) == 1:
        return True
    # Already-filled banner: every (or most) cells repeat the same caption.
    if len(non_empty) >= max(2, int(len(cells) * 0.6)):
        return bool(_TABLE_BANNER_RE.match(label)) or len(label) >= 28
    return bool(_TABLE_BANNER_RE.match(label)) and len(non_empty) >= len(cells) * 0.5


def _row_banner_label(row: Sequence[Any]) -> Optional[str]:
    """Text of a full-width in-grid banner, or None if the row is not one."""
    if not _row_is_full_width_banner(row):
        return None
    non_empty = [_cell_str(v) for v in row if _cell_str(v)]
    return non_empty[0] if non_empty else None


def _is_table_id_only(label: str) -> bool:
    """True for short document-id banners like ``TABLE: B-6`` / ``TABLE- B-1``."""
    s = _cell_str(label)
    return bool(s) and bool(_TABLE_ID_ONLY_RE.match(s))


def _is_descriptive_in_grid_title(label: str) -> bool:
    """
    True when text looks like a descriptive table caption (not a short id,
    unit strip, or stub header word).
    """
    s = _cell_str(label)
    if not s:
        return False
    if _is_table_id_only(s):
        return False
    if _UNIT_GROUP_RE.match(s):
        return False
    if _looks_like_column_list_banner(s):
        return False
    m = _TABLE_ID_THEN_TITLE_RE.match(s)
    if m:
        s = _cell_str(m.group("title"))
        if not s:
            return False
    words = s.split()
    if len(s) < 18 and len(words) < 4:
        return False
    # Single/short stub labels that happen to colspan are not titles.
    if len(words) <= 2 and len(s) < 30:
        return False
    letter_chars = sum(1 for c in s if c.isalpha())
    if letter_chars < max(10, int(len(s) * 0.45)):
        return False
    if sum(1 for w in words if _is_numeric_cell(w)) >= max(2, len(words) // 2):
        return False
    return True


_SUBTITLE_STUB_RE = re.compile(
    r"^(?:"
    r"sl\.?\s*no\.?|s\.?\s*no\.?|sno|total|all|male|female|males|females|"
    r"mother\s*age|birth\s*order|particulars|year|age|sex"
    r")$",
    re.I,
)


def _is_in_grid_subtitle(label: str) -> bool:
    """Short scope/category banner under the main title (e.g. RELIGION-OTHERS).

    These are too short for ``_is_descriptive_in_grid_title`` but still belong
    in the display title so sibling TABLES (same B-15 caption, different
    religion) stay distinguishable.
    """
    s = _cell_str(label)
    if not s:
        return False
    if _is_table_id_only(s) or _UNIT_GROUP_RE.match(s):
        return False
    if _looks_like_column_list_banner(s):
        return False
    if _is_descriptive_in_grid_title(s):
        return True
    if _SUBTITLE_STUB_RE.match(s):
        return False
    words = s.split()
    if len(s) < 4 or len(s) > 64 or len(words) > 8:
        return False
    # Prefer label-like tokens: letters with optional hyphen/paren scope.
    letter_chars = sum(1 for c in s if c.isalpha())
    if letter_chars < 3:
        return False
    if sum(1 for w in words if _is_numeric_cell(w)) >= max(2, len(words) // 2):
        return False
    return True


def _looks_like_column_list_banner(label: str) -> bool:
    """Comma/slash-separated field lists that belong in headers, not titles."""
    s = _cell_str(label)
    if not s:
        return False
    parts = [p.strip() for p in re.split(r"[,;/|]", s) if p.strip()]
    if len(parts) < 2:
        return False
    shortish = sum(1 for p in parts if len(p) <= 40 and len(p.split()) <= 5)
    return shortish >= max(2, len(parts) - 1) and len(s) <= 160


def extract_in_grid_caption(
    rows: Optional[List[List[Any]]],
) -> dict:
    """
    Extract table id + descriptive title from leading full-width banner rows.

    Common in CRS / vital-statistics tables where ``TABLE: B-12`` is the first
    ruled row, the next full-width row is the long caption, and an optional
    subtitle banner follows (e.g. ``MOTHER EDUCATION (NOT STATED)``).

    Returns
      title            – descriptive caption (subtitles joined with " — ")
      table_id_label   – short TABLE/STATEMENT/… id when present
      rows_consumed    – body start index (row after last consumed banner); 0 if none
    """
    out: dict = {"title": None, "table_id_label": None, "rows_consumed": 0}
    if not rows:
        return out
    n_cols = max((len(r) for r in rows), default=0)
    if n_cols < 2:
        return out

    banners: List[Tuple[int, str]] = []
    for i, row in enumerate(rows[:12]):
        padded = _pad_row(row, n_cols)
        if _blank(padded):
            continue
        label = _row_banner_label(padded)
        if label:
            banners.append((i, label))
            continue
        break

    if not banners:
        return out

    def _descriptive_run(start: int) -> List[Tuple[int, str]]:
        """Consecutive descriptive / subtitle banners starting at ``start``."""
        run: List[Tuple[int, str]] = []
        for pair in banners[start:]:
            _idx, b = pair
            if _is_table_id_only(b) or _UNIT_GROUP_RE.match(b):
                break
            # Primary long caption OR short scope line (RELIGION-OTHERS, URBAN).
            if _is_descriptive_in_grid_title(b) or _is_in_grid_subtitle(b):
                run.append(pair)
                continue
            break
        return run

    def _finish(
        table_id: Optional[str],
        title_pairs: List[Tuple[int, str]],
        fallback_end_i: int,
    ) -> dict:
        out["table_id_label"] = table_id
        if title_pairs:
            # Prefer a primary caption. Do not swallow column-list banners
            # (e.g. "Scheme name, beneficiaries, budget") into the title — those
            # must remain in the body so headers/data extract correctly.
            # Allow one short subtitle (RELIGION-OTHERS / URBAN) and/or wrapped
            # title continuations under the main caption.
            kept: List[Tuple[int, str]] = []
            used_subtitle = False
            wrap_continuation = False
            for i, pair in enumerate(title_pairs):
                _idx, lab = pair
                if i == 0:
                    kept.append(pair)
                    continue
                if _looks_like_column_list_banner(lab):
                    break
                prev = kept[-1][1]
                # Mid-phrase wrap: previous banner ends with a connector word.
                if (
                    re.search(r"\b(?:FOR|AND|OF|THE|BY|WITH|TO|IN|OR|NOT|A|AN)\s*$", prev, re.I)
                    and (_is_descriptive_in_grid_title(lab) or _is_in_grid_subtitle(lab))
                ):
                    kept.append(pair)
                    wrap_continuation = True
                    continue
                short_subtitle = (
                    _is_in_grid_subtitle(lab)
                    and len(lab) <= 48
                    and lab.count(",") < 2
                    and len(lab.split()) <= 8
                )
                if short_subtitle and not used_subtitle and not wrap_continuation:
                    kept.append(pair)
                    used_subtitle = True
                    break
                # Long descriptive follow-on = wrapped title continuation.
                if _is_descriptive_in_grid_title(lab) and len(prev) >= 40:
                    kept.append(pair)
                    wrap_continuation = True
                    continue
                break
            if kept:
                primary = kept[0][1]
                rest = [lab for _i, lab in kept[1:]]
                if not rest:
                    out["title"] = primary
                elif wrap_continuation:
                    out["title"] = " ".join([primary, *rest])
                else:
                    out["title"] = " — ".join([primary, *rest])
                out["rows_consumed"] = kept[-1][0] + 1
            else:
                out["rows_consumed"] = fallback_end_i + 1
        else:
            out["rows_consumed"] = fallback_end_i + 1
        return out

    labels = [lab for _i, lab in banners]
    first = labels[0]

    if _is_table_id_only(first):
        return _finish(first, _descriptive_run(1), banners[0][0])

    combined = _TABLE_ID_THEN_TITLE_RE.match(first)
    if combined:
        title_part = _cell_str(combined.group("title"))
        if _is_descriptive_in_grid_title(title_part):
            # Treat combined cell as the first title part, then more banners.
            rest = _descriptive_run(1)
            pairs = [(banners[0][0], title_part)] + rest
            return _finish(_cell_str(combined.group("id")), pairs, banners[0][0])

    if _is_descriptive_in_grid_title(first):
        return _finish(None, _descriptive_run(0), banners[0][0])

    for i, b in enumerate(labels):
        if not _is_table_id_only(b):
            continue
        return _finish(b, _descriptive_run(i + 1), banners[i][0])

    # Leading full-width rows we couldn't classify — skip so they aren't headers.
    return _finish(None, [], banners[-1][0])


def _row_is_text_header(
    row: Sequence[Any],
    *,
    continuation: bool = False,
    parent_row: Optional[Sequence[Any]] = None,
) -> bool:
    """Primary header row: mostly non-numeric labels / group banners."""
    cells = list(row)
    non_empty = [v for v in cells if _cell_str(v)]
    if not non_empty:
        return False
    nums = sum(1 for v in non_empty if _is_numeric_cell(v))
    if nums > len(non_empty) * 0.35:
        return False
    if any(_is_measurement_number(v) for v in non_empty):
        return False
    if continuation:
        # Extra header rows are usually sparse (colspan leftovers / leaf labels).
        # A fully dense row after the first header is almost always data.
        empty_frac = 1.0 - (len(non_empty) / max(len(cells), 1))
        if empty_frac < 0.15:
            return False
        # Section titles in the body often leave measure cells blank — reject when
        # stub/identity columns are newly populated (e.g. "A" under Sl. No.).
        if parent_row is not None:
            kinds = _parent_col_kinds(parent_row)
            for i, kind in enumerate(kinds):
                if i >= len(cells) or kind != "stub":
                    continue
                ps = _cell_str(parent_row[i]) if i < len(parent_row) else ""
                cs = _cell_str(cells[i])
                if cs and cs.upper() != ps.upper():
                    return False
    return True


def _parent_col_kinds(parent_row: Sequence[Any]) -> List[str]:
    """
    Classify top-header cells by structure:
      - stub: identity label beside another distinct label (Sl. No., Sex, …)
      - group: colspan banner over leaf codes (empties after it, or the same
        label repeated across adjacent cells from a pre-filled extract)
      - span: empty cell inside a colspan
    """
    n = len(parent_row)
    kinds: List[str] = ["span"] * n
    for i in range(n):
        ps = _cell_str(parent_row[i])
        if not ps:
            continue
        j = i + 1
        while j < n and not _cell_str(parent_row[j]):
            j += 1
        kinds[i] = "group" if j > i + 1 else "stub"

    # Pre-filled colspan: the same parent label repeated across adjacent cells.
    i = 0
    while i < n:
        ps = _cell_str(parent_row[i])
        if not ps:
            i += 1
            continue
        j = i + 1
        while j < n and _cell_str(parent_row[j]).upper() == ps.upper():
            j += 1
        if j > i + 1:
            for k in range(i, j):
                kinds[k] = "group"
        i = j
    return kinds


def _row_looks_like_data(
    row: Sequence[Any],
    parent_row: Optional[Sequence[Any]] = None,
) -> bool:
    """True when a row is clearly body data, not another header strip."""
    non_empty = [v for v in row if _cell_str(v)]
    if not non_empty:
        return False
    measurements = sum(1 for v in non_empty if _is_measurement_number(v))
    nums = sum(1 for v in non_empty if _is_numeric_cell(v))
    if parent_row is not None:
        kinds = _parent_col_kinds(parent_row)
        stub_new = 0
        for i, kind in enumerate(kinds):
            if i >= len(row) or kind != "stub":
                continue
            ps = _cell_str(parent_row[i]) if i < len(parent_row) else ""
            cs = _cell_str(row[i])
            if cs and cs.upper() != ps.upper():
                stub_new += 1
        if stub_new > 0 and (measurements >= 1 or any(len(_cell_str(v)) > _LEAF_MAX_LEN for v in non_empty)):
            return True
        if stub_new >= 2:
            return True
    if measurements >= 2 and nums >= max(2, int(len(non_empty) * 0.5)):
        return True
    return False


def _row_is_subheader(
    row: Sequence[Any],
    parent_row: Optional[Sequence[Any]] = None,
) -> bool:
    """
    Extra header strip under a parent row: leaf codes (2019, Male) or mid-level
    category labels (Urban, Primary). Rejects body/data rows.
    """
    if _row_is_leaf_header(row, parent_row):
        return True
    non_empty = [v for v in row if _cell_str(v)]
    if len(non_empty) < 1:
        return False
    if sum(1 for v in non_empty if _is_measurement_number(v)) >= 2:
        return False
    if _row_looks_like_data(row, parent_row):
        return False
    if parent_row is not None:
        kinds = _parent_col_kinds(parent_row)
        for i, kind in enumerate(kinds):
            if i >= len(row) or kind != "stub":
                continue
            ps = _cell_str(parent_row[i]) if i < len(parent_row) else ""
            cs = _cell_str(row[i])
            if cs and cs.upper() != ps.upper():
                return False
    short = sum(1 for v in non_empty if len(_cell_str(v)) <= 40)
    return short >= max(1, int(len(non_empty) * 0.7))


def resolve_column_headers(header_matrix: List[List[Any]], n_cols: int) -> List[dict]:
    """
    Resolve multi-row headers into a full top→leaf path per column.

    Each result:
      name          – leaf label (last path element)
      header_group  – immediate parent (compat; None if single-level)
      header_path   – full hierarchy ["L1", "L2", …, leaf] (length 1..N)
    """
    rows_in = [r for r in header_matrix if not _row_is_full_width_banner(r)]
    if not rows_in:
        rows_in = list(header_matrix)

    raw_top = _pad_row(rows_in[0], n_cols) if rows_in else []
    kinds = _parent_col_kinds(raw_top) if rows_in else []

    rows = _fill_header_matrix(rows_in, n_cols)
    if not rows:
        return [
            {"name": f"Col_{i + 1}", "header_group": None, "header_path": [f"Col_{i + 1}"]}
            for i in range(n_cols)
        ]

    out: List[dict] = []
    for i in range(n_cols):
        path: List[str] = []
        for row in rows:
            lab = row[i] if i < len(row) else ""
            if not lab:
                continue
            if _TABLE_BANNER_RE.match(lab.strip()):
                continue
            if path and path[-1].upper() == lab.upper():
                continue
            path.append(lab)

        if not path:
            path = [f"Col_{i + 1}"]

        kind = kinds[i] if i < len(kinds) else "stub"
        # Identity/stub columns must stay single-level even if a leaf token spilled under them.
        if kind == "stub" and len(path) > 1 and path[0].upper() != path[-1].upper():
            path = [path[0]]

        name = path[-1]
        group = path[-2] if len(path) >= 2 else None
        out.append({"name": name, "header_group": group, "header_path": path})
    return out


def _row_is_leaf_header(
    row: Sequence[Any],
    parent_row: Optional[Sequence[Any]] = None,
) -> bool:
    """
    Leaf header row under spanning parents: short codes across many columns.

    Structural contrast with a data row (domain-agnostic):
      - leaf → short tokens; stub columns left blank; few/no large measurements
      - data → values under stub columns and/or large numbers / long prose
    """
    non_empty = [v for v in row if _cell_str(v)]
    if len(non_empty) < 2:
        return False

    short = sum(1 for v in non_empty if len(_cell_str(v)) <= _LEAF_MAX_LEN)
    if short < len(non_empty) * 0.75:
        return False

    if sum(1 for v in non_empty if _is_measurement_number(v)) >= 2:
        return False

    # A strip of identical numbers (especially all zeros) is body data, not codes.
    # Real leaf rows are diverse: 1,2,3… or M,F,O or 2001,2011.
    unique_vals = {_cell_str(v) for v in non_empty}
    if len(unique_vals) == 1 and _is_numeric_cell(next(iter(non_empty))):
        return False

    long_prose = sum(1 for v in non_empty if len(_cell_str(v)) > _LEAF_MAX_LEN)
    if long_prose >= 1 and sum(1 for v in non_empty if _is_measurement_number(v)) >= 1:
        return False

    leafish = sum(1 for v in non_empty if _is_leaf_header_token(v))
    if leafish < max(2, int(len(non_empty) * 0.55)):
        return False

    if parent_row is not None:
        kinds = _parent_col_kinds(parent_row)
        stub_populated = 0
        stub_blank = 0
        group_codes = 0
        for i, kind in enumerate(kinds):
            if i >= len(row):
                break
            ps = _cell_str(parent_row[i]) if i < len(parent_row) else ""
            cs = _cell_str(row[i])
            if kind == "stub":
                if not cs:
                    stub_blank += 1
                elif cs.upper() == ps.upper():
                    continue
                else:
                    # Real data fills identity/stub columns; leaf strips leave them empty.
                    stub_populated += 1
            elif kind == "group" and cs and _is_leaf_header_token(row[i]):
                group_codes += 1
        if stub_populated > 0:
            return False
        # Classic colspan leaf strip: blank stubs + codes under at least one group.
        if stub_blank == 0 and group_codes == 0:
            return False

    return True


_MAX_HEADER_ROWS = 8


def detect_header_rows(body: List[List[Any]], n_cols: int) -> Tuple[int, List[int]]:
    """Leading header-row count plus indices of banner / '(1)(2)(3)' rows to skip.

    Absorbs an arbitrary number of header levels (1..N) until a data row appears.
    Index-strip skips apply only before the first body-data row so blank-stub
    percentage rows like ``("", "(10.6)", "(13.6)", …)`` are never discarded.
    """
    scan = body[: max(_MAX_HEADER_ROWS + 2, 10)]
    skip_rows: List[int] = []
    seen_data = False
    for i, row in enumerate(scan):
        if _row_is_full_width_banner(row):
            if not seen_data:
                skip_rows.append(i)
            continue
        non_empty = [v for v in row if _cell_str(v)]
        if not non_empty:
            continue
        # Body data (year + counts, or blank-stub percentage shares) ends the
        # header-adjacent skip window.
        if (
            _row_looks_like_data(row, None)
            or sum(1 for v in non_empty if _is_measurement_number(v)) >= 2
        ):
            seen_data = True
            continue
        if seen_data:
            continue
        col_nums = sum(1 for v in non_empty if _COL_NUM_RE.match(_cell_str(v)))
        if col_nums > len(non_empty) * 0.5:
            skip_rows.append(i)
            continue
        # Pure 1,2,3,…,N index row (no parentheses) sitting under the header.
        if (
            len(non_empty) >= max(3, int(n_cols * 0.6))
            and all(_BARE_INDEX_RE.match(_cell_str(v)) for v in non_empty)
        ):
            try:
                nums = [int(_cell_str(v)) for v in non_empty]
            except ValueError:
                nums = []
            if nums and nums == list(range(1, len(nums) + 1)):
                skip_rows.append(i)

    header_count = 0
    root_header_row: Optional[Sequence[Any]] = None
    levels = 0
    for i, row in enumerate(scan):
        if i in skip_rows:
            continue
        if _blank(row):
            break
        if levels >= _MAX_HEADER_ROWS:
            break
        if header_count > 0 and _row_looks_like_data(row, root_header_row):
            break

        is_continuation = header_count > 0
        if _row_is_text_header(
            row,
            continuation=is_continuation,
            parent_row=root_header_row,
        ):
            header_count = i + 1
            if root_header_row is None:
                root_header_row = row
            levels += 1
            continue

        if header_count > 0 and _row_is_subheader(row, root_header_row):
            header_count = i + 1
            levels += 1
            continue

        break

    if header_count <= 0:
        for i, row in enumerate(scan):
            if i not in skip_rows and not _blank(row):
                header_count = i + 1
                break
        header_count = max(header_count, 1)

    return header_count, skip_rows


def _fill_header_matrix(header_matrix: List[List[Any]], n_cols: int) -> List[List[str]]:
    """
    Resolve rowspan then colspan empties inside the header block.

    Vertical first (rowspan stubs), then horizontal (colspan group banners).
    """
    rows: List[List[Any]] = [_pad_row(r, n_cols) for r in header_matrix]
    for c in range(n_cols):
        last = ""
        for r in range(len(rows)):
            s = _cell_str(rows[r][c])
            if s:
                last = s
                rows[r][c] = s
            elif last:
                rows[r][c] = last
            else:
                rows[r][c] = ""
    filled: List[List[str]] = []
    for row in rows:
        out: List[str] = []
        last = ""
        for v in row:
            s = _cell_str(v)
            if s:
                last = s
                out.append(s)
            elif last:
                out.append(last)
            else:
                out.append("")
        filled.append(out)
    return filled


def flatten_headers(header_matrix: List[List[Any]], n_cols: int) -> List[str]:
    """Flat display names when a single string is required."""
    resolved = resolve_column_headers(header_matrix, n_cols)
    names: List[str] = []
    for col in resolved:
        path = [str(p) for p in (col.get("header_path") or []) if str(p).strip()]
        if len(path) >= 2:
            names.append(" / ".join(path))
        else:
            names.append(col["name"])
    return names


def _uniquify_columns(names: List[str]) -> List[str]:
    seen: dict[str, int] = {}
    out: List[str] = []
    for name in names:
        base = name or "Col"
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base} ({n + 1})")
    return out


def _split_hybrid_leaf_data_row(
    row: Sequence[Any],
    parent_row: Sequence[Any],
    n_cols: int,
) -> Tuple[Optional[List[Any]], Optional[List[Any]]]:
    """
    Some extracts put leaf codes (2001, 2011) on the same row as the first
    section stub (A + title). Split into a leaf-header row and a data row.

    Must NOT fire on real data rows. Small integers under group columns
    (0, 86, 32, …) are counts — only calendar years and non-numeric short
    codes are valid hybrid leaf halves.
    """
    parent = _pad_row(parent_row, n_cols)
    cells = _pad_row(row, n_cols)
    kinds = _parent_col_kinds(parent)
    leaf_row: List[Any] = [None] * n_cols
    data_row: List[Any] = [None] * n_cols
    found_leaf = False
    found_stub = False
    group_vals: List[Any] = []

    for i, kind in enumerate(kinds):
        val = cells[i]
        if kind == "stub":
            if _cell_str(val):
                data_row[i] = val
                found_stub = True
        else:
            # group or span under a colspan parent
            if _cell_str(val):
                group_vals.append(val)
            # Years always qualify; other leaf tokens must be non-numeric
            # (Male, Rural, …). Plain ints are treated as data counts.
            if _is_year_code(val) or (
                _is_leaf_header_token(val)
                and not _is_numeric_cell(val)
                and not _is_measurement_number(val)
            ):
                leaf_row[i] = val
                found_leaf = True
            elif _cell_str(val):
                data_row[i] = val

    if not (found_leaf and found_stub):
        return None, None
    # Mixed measure + leaf-like ints ⇒ data row (e.g. vital rates 18.6 … 35, 13).
    if any(_is_measurement_number(v) for v in group_vals):
        return None, None
    leaf_count = sum(1 for v in leaf_row if _cell_str(v))
    if leaf_count < 2:
        return None, None
    # Almost all non-empty group cells should be leaf tokens (Census years, etc.).
    nonempty_group = sum(1 for v in group_vals if _cell_str(v))
    if nonempty_group and leaf_count < max(2, int(nonempty_group * 0.75)):
        return None, None
    # Identical repeated values under groups are counts, not category labels.
    unique_leaves = {_cell_str(v) for v in leaf_row if _cell_str(v)}
    if len(unique_leaves) == 1:
        return None, None
    return leaf_row, data_row


def _row_table_id_label(row: Sequence[Any]) -> Optional[str]:
    """Return the TABLE/STATEMENT/ANNEX id if this row is a caption marker."""
    non_empty = [_cell_str(v) for v in row if _cell_str(v)]
    if not non_empty:
        return None
    label = non_empty[0]
    # Prefer the short id when id + title share one cell.
    combined = _TABLE_ID_THEN_TITLE_RE.match(label)
    if combined and _is_descriptive_in_grid_title(combined.group("title")):
        return _cell_str(combined.group("id"))
    if _is_table_id_only(label) or _TABLE_BANNER_RE.match(label):
        return label
    return None


def _split_hybrid_table_marker_row(
    row: Sequence[Any],
) -> Tuple[Optional[List[Any]], Optional[List[Any]]]:
    """
    Detect a Y-collision row: table id on the left, measure values on the right
    (previous table's last totals sharing a scanline with the next caption).

    Returns (banner_row, numeric_tail_row). numeric_tail belongs to the
    previous table; banner_row starts the next one.
    """
    cells = list(row)
    if len(cells) < 3:
        return None, None
    label = _row_table_id_label(cells)
    if not label:
        return None, None
    # Locate the banner cell; everything after the stub block may be numeric.
    banner_idx = next((i for i, v in enumerate(cells) if _cell_str(v) == label), 0)
    numeric_idxs = [
        i for i in range(banner_idx + 1, len(cells))
        if _cell_str(cells[i]) and _is_numeric_cell(cells[i])
    ]
    if len(numeric_idxs) < 2:
        return None, None
    # Require that non-banner non-empty cells are predominantly numeric.
    other_nonempty = [
        i for i, v in enumerate(cells)
        if i != banner_idx and _cell_str(v)
    ]
    if not other_nonempty:
        return None, None
    num_frac = sum(1 for i in other_nonempty if _is_numeric_cell(cells[i])) / len(other_nonempty)
    if num_frac < 0.75:
        return None, None

    banner_row = [None] * len(cells)
    banner_row[banner_idx] = cells[banner_idx]
    # Keep a short qualifier next to the id (e.g. "(RURAL)") if present.
    for i in other_nonempty:
        if not _is_numeric_cell(cells[i]) and len(_cell_str(cells[i])) <= 24:
            banner_row[i] = cells[i]

    numeric_row = [None] * len(cells)
    for i in other_nonempty:
        if _is_numeric_cell(cells[i]):
            numeric_row[i] = cells[i]
    return banner_row, numeric_row


def _row_is_new_table_marker(row: Sequence[Any]) -> bool:
    """True when a row is an in-grid TABLE/STATEMENT caption starting a block."""
    if _row_table_id_label(row) is None:
        return False
    hybrid_banner, hybrid_nums = _split_hybrid_table_marker_row(row)
    if hybrid_banner is not None:
        return True
    # Classic full-width / near-empty caption row (not a long descriptive title
    # alone — those lack the TABLE/STATEMENT id matched above).
    non_empty = [_cell_str(v) for v in row if _cell_str(v)]
    if len(non_empty) == 1:
        return True
    # Id + short qualifier only.
    if len(non_empty) <= 3 and all(len(s) <= 40 for s in non_empty[1:]):
        return True
    return _row_is_full_width_banner(row)


def split_extracted_rows_on_table_markers(
    rows: Optional[List[List[Any]]],
) -> List[Tuple[List[List[Any]], int, int]]:
    """
    Split a pymupdf extract grid that glued consecutive physical tables.

    Statistical PDFs often place two ruled tables on one page with only a thin
    gap; pymupdf returns one bbox whose rows contain a second ``TABLE: …``
    banner mid-grid. Without a split, auto-accept and the LLM both emit one
    record with the second title/header sitting in the first table's body.

    Returns a list of ``(segment_rows, start_idx, end_idx)`` covering
    ``rows[start:end]`` (end exclusive). Single-table grids return one segment.
    """
    if not rows:
        return []

    n_cols = max((len(r) for r in rows), default=0)
    if n_cols == 0:
        return []
    padded = [_pad_row(r, n_cols) for r in rows]

    markers: List[int] = []
    hybrid_fix: dict = {}
    for i, row in enumerate(padded):
        if not _row_is_new_table_marker(row):
            continue
        banner, numeric_tail = _split_hybrid_table_marker_row(row)
        if banner is not None and numeric_tail is not None:
            padded[i] = banner
            hybrid_fix[i] = numeric_tail
        markers.append(i)

    if len(markers) <= 1 and (not markers or markers[0] == 0):
        return [(padded, 0, len(padded))]

    # Include a leading block that has no caption marker (rare).
    starts = list(markers)
    if starts[0] != 0:
        starts = [0] + starts

    segments: List[Tuple[List[List[Any]], int, int]] = []
    for j, start in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(padded)
        # Hybrid numeric tail at `end` belongs to this segment (previous table).
        chunk = [list(r) for r in padded[start:end]]
        if end in hybrid_fix and chunk:
            # Marker row at `end` was replaced with banner-only; its numbers
            # were captured in hybrid_fix and should close the prior table.
            chunk.append(list(hybrid_fix[end]))
        # Drop trailing blank rows.
        while chunk and _blank(chunk[-1]):
            chunk.pop()
        # Drop leading blanks (gap between tables).
        while chunk and _blank(chunk[0]):
            chunk.pop(0)
            start += 1
        if len(chunk) >= 2:
            segments.append((chunk, start, end))
    return segments or [(padded, 0, len(padded))]


def repair_glued_numeric_cells(rows: List[List[Any]]) -> List[List[Any]]:
    """
    Spread space-joined numbers into adjacent empty cells.

    pymupdf sometimes packs several measure values into one cell and leaves
    neighbouring period columns blank. Prefer expanding into following empty
    cells; if those are insufficient, use preceding empties (or the combined
    empty window). Only expands when every token is numeric and there are
    enough empty slots — skips catastrophic merges that won't fit.
    """
    if not rows:
        return rows
    n_cols = max((len(r) for r in rows), default=0)
    out = [_pad_row(r, n_cols) for r in rows]
    for row in out:
        j = 0
        while j < n_cols:
            parts = _glued_numeric_parts(row[j])
            if not parts:
                j += 1
                continue
            n_parts = len(parts)
            empty_after = 0
            for k in range(j + 1, n_cols):
                if _cell_str(row[k]):
                    break
                empty_after += 1
            empty_before = 0
            for k in range(j - 1, -1, -1):
                if _cell_str(row[k]):
                    break
                empty_before += 1

            if n_parts <= empty_after + 1:
                start = j
            elif n_parts <= empty_before + 1:
                start = j - (n_parts - 1)
            elif n_parts <= empty_before + empty_after + 1:
                # Right-align into the empty window around the glued cell so
                # leading blanks (unused earlier periods) stay empty.
                window_end = j + empty_after
                start = window_end - n_parts + 1
            else:
                j += 1
                continue

            for t, part in enumerate(parts):
                row[start + t] = part
            if not (start <= j < start + n_parts):
                row[j] = None
            j = start + n_parts
    return out


def _glued_numeric_parts(cell: Any) -> Optional[List[str]]:
    s = _cell_str(cell)
    if not s or " " not in s:
        return None
    parts = s.split()
    if len(parts) < 2:
        return None
    if not all(_is_numeric_cell(p) for p in parts):
        return None
    return parts


_SEX_TOKEN_RE = re.compile(r"^[MF]$", re.I)
_SEX_HEADER_RE = re.compile(r"^(sex|gender)$", re.I)
# Measure/OCR glue on Sex cells: "0M", "12F", "eM".
_SEX_GLUE_RE = re.compile(r"^[\d\.]*[a-z]?[MFmf][\d\.]*$")


def _cell_raw_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v).replace("\r\n", "\n").replace("\r", "\n")


def _normalize_sex_token(t: str) -> Optional[str]:
    """Return 'M'/'F' from a clean or lightly-glued sex cell line."""
    s = (t or "").strip()
    if not s:
        return None
    if _SEX_TOKEN_RE.match(s):
        return s.upper()
    if len(s) <= 4 and _SEX_GLUE_RE.match(s):
        letters = re.findall(r"[MFmf]", s)
        if len(letters) == 1:
            return letters[0].upper()
    return None


def _sex_tokens_from_cell(v: Any) -> Optional[List[str]]:
    """Return ['M','F',…] when a cell is a stacked/space-joined sex strip."""
    raw = _cell_raw_text(v)
    if not raw.strip():
        return None
    # Prefer newline stacking (pymupdf collapsed M/F rows).
    line_toks = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if len(line_toks) >= 2:
        normalized = [_normalize_sex_token(t) for t in line_toks]
        if all(normalized):
            return normalized  # type: ignore[return-value]
    # Flattened to spaces by an earlier pass / text strategy.
    parts = _cell_str(v).split()
    if len(parts) >= 2:
        normalized = [_normalize_sex_token(p) for p in parts]
        if all(normalized):
            return normalized  # type: ignore[return-value]
    return None


def _find_sex_column(rows: List[List[Any]], n_cols: int) -> Optional[int]:
    """Prefer a header named Sex/Gender; else the densest M/F stack column."""
    for row in rows[:6]:
        for c in range(min(len(row), n_cols)):
            if _SEX_HEADER_RE.match(_cell_str(row[c])):
                return c
    best_c: Optional[int] = None
    best_n = 0
    for row in rows:
        for c in range(min(len(row), n_cols)):
            toks = _sex_tokens_from_cell(row[c])
            if toks and len(toks) > best_n:
                best_n = len(toks)
                best_c = c
    return best_c if best_n >= 2 else None


def _coalesce_split_cell_values(left: Any, right: Any) -> Optional[str]:
    """Merge two cells from phantom split columns into one value."""
    a, b = _cell_str(left), _cell_str(right)
    if not a:
        return b or None
    if not b:
        return a or None
    if a == b:
        return a
    if a in b:
        return b
    if b in a:
        return a
    # Mid-word split across adjacent phantom columns ("Septicae" + "mia",
    # "originati" + "ng in the"). Glue when the right fragment is a short
    # lowercase/continuation tail; otherwise space-join.
    if a[-1].isalnum() and b[0].isalnum():
        if b[0].islower() or (len(b) <= 6 and " " not in b and not b[0].isdigit()):
            return f"{a}{b}"
    return f"{a} {b}".strip()


def _header_path_key(meta: Optional[dict], fallback_name: str) -> Tuple[str, ...]:
    if not meta:
        return (str(fallback_name or "").strip().lower(),)
    path = [
        str(p).strip().lower()
        for p in (meta.get("header_path") or [])
        if str(p).strip()
    ]
    if path:
        return tuple(path)
    name = str(meta.get("name") or fallback_name or "").strip().lower()
    # Strip uniquify suffix " (2)" / " (3)" so phantoms group together.
    name = re.sub(r"\s*\(\d+\)\s*$", "", name).strip()
    group = str(meta.get("header_group") or "").strip().lower() or None
    return (group, name) if group else (name,)


def coalesce_phantom_grid_columns(df):
    """Merge adjacent columns that share the same header path (PDF grid phantoms).

    PyMuPDF often invents empty interstitial columns inside a wide Cause cell or
    under Male/Female/Total, yielding Cause/(2)/(3) and Male/(2)/(3) with values
    scattered or duplicated. Collapse each identical-path run into one column.
    """
    import pandas as pd

    if df is None or getattr(df, "empty", True) or df.shape[1] < 2:
        return df

    meta = list(getattr(df, "attrs", {}).get("dhara_column_meta") or [])
    if meta and len(meta) != df.shape[1]:
        meta = []

    keys = [
        _header_path_key(meta[i] if meta else None, str(df.columns[i]))
        for i in range(df.shape[1])
    ]

    # Build runs of identical keys.
    runs: List[Tuple[int, int]] = []
    start = 0
    for i in range(1, df.shape[1] + 1):
        if i == df.shape[1] or keys[i] != keys[start]:
            runs.append((start, i))
            start = i

    if all((end - start) == 1 for start, end in runs):
        # Still drop empty parent-as-leaf columns (name == neighbour's group).
        return _drop_empty_parent_leaf_columns(df)

    new_cols: List[Any] = []
    new_meta: List[dict] = []
    series_list: List[List[Optional[str]]] = []

    for start, end in runs:
        if end - start == 1:
            new_cols.append(df.columns[start])
            if meta:
                new_meta.append(meta[start])
            series_list.append([
                _cell_str(v) or None for v in df.iloc[:, start].tolist()
            ])
            continue
        # Coalesce body cells left→right across the phantom run.
        merged: List[Optional[str]] = []
        for r in range(df.shape[0]):
            val: Optional[str] = None
            for c in range(start, end):
                val = _coalesce_split_cell_values(val, df.iloc[r, c])
            merged.append(val)
        # Prefer the first non-empty-named leaf; strip uniquify suffix for display.
        leaf = str(df.columns[start])
        leaf = re.sub(r"\s*\(\d+\)\s*$", "", leaf).strip() or leaf
        new_cols.append(leaf)
        if meta:
            m = dict(meta[start])
            m["name"] = leaf
            new_meta.append(m)
        series_list.append(merged)

    out = pd.DataFrame(
        [list(vals) for vals in zip(*series_list)] if series_list else [],
        columns=new_cols,
    )
    # Preserve attrs
    for key, val in getattr(df, "attrs", {}).items():
        if key == "dhara_column_meta":
            continue
        out.attrs[key] = val
    if new_meta and len(new_meta) == out.shape[1]:
        out.attrs["dhara_column_meta"] = new_meta
    return _drop_empty_parent_leaf_columns(out)


def _drop_empty_parent_leaf_columns(df):
    """Drop all-null columns whose name is only a parent of a neighbour leaf.

    Also right-shift measure values that landed in a parent-as-leaf column
    (common when PyMuPDF parks Male under the spanning 'No. of …' cell).
    """
    import pandas as pd

    if df is None or getattr(df, "empty", True) or df.shape[1] < 2:
        return df
    meta = list(getattr(df, "attrs", {}).get("dhara_column_meta") or [])
    if meta and len(meta) != df.shape[1]:
        meta = []

    # Right-shift: parent leaf with values + children under that group where the
    # last child is empty → rotate values into the children.
    if meta:
        i = 0
        while i < df.shape[1]:
            m = meta[i]
            parent_name = re.sub(r"\s*\(\d+\)\s*$", "", str(m.get("name") or "")).strip()
            parent_low = parent_name.lower()
            # Parent-as-leaf: no header_group (or group == self) and later cols use it as group.
            own_group = str(m.get("header_group") or "").strip()
            if own_group and own_group.lower() != parent_low:
                i += 1
                continue
            child_idxs: List[int] = []
            j = i + 1
            while j < df.shape[1]:
                cj = str(meta[j].get("header_group") or "").strip().lower()
                if cj != parent_low:
                    break
                child_idxs.append(j)
                j += 1
            if len(child_idxs) >= 2:
                parent_vals = [_cell_str(v) for v in df.iloc[:, i].tolist()]
                last_vals = [_cell_str(v) for v in df.iloc[:, child_idxs[-1]].tolist()]
                parent_fill = sum(1 for v in parent_vals if v)
                last_fill = sum(1 for v in last_vals if v)
                if parent_fill >= 2 and last_fill == 0:
                    # Right-shift: [parent_vals, M, F, T_empty] → [empty, parent_vals, M, F]
                    block = [i] + child_idxs
                    for r in range(df.shape[0]):
                        vals = [_cell_str(df.iloc[r, c]) or None for c in block]
                        if not any(vals):
                            continue
                        shifted = [None] + vals[:-1]
                        for c, val in zip(block, shifted):
                            df.iloc[r, c] = val
            i = j if child_idxs else i + 1
    else:
        i = 0

    groups = set()
    for m in meta:
        g = str(m.get("header_group") or "").strip().lower()
        if g:
            groups.add(g)
        path = m.get("header_path") or []
        if len(path) >= 2:
            groups.add(str(path[-2]).strip().lower())

    keep: List[int] = []
    for idx, name in enumerate(df.columns):
        series = df.iloc[:, idx]
        all_null = bool(series.isna().all()) or all(not _cell_str(v) for v in series.tolist())
        nm = re.sub(r"\s*\(\d+\)\s*$", "", str(name)).strip().lower()
        if all_null and nm in groups:
            continue
        keep.append(idx)
    if len(keep) == df.shape[1]:
        return df
    if not keep:
        return df
    out = df.iloc[:, keep].copy()
    for key, val in getattr(df, "attrs", {}).items():
        if key == "dhara_column_meta":
            continue
        out.attrs[key] = val
    if meta:
        out.attrs["dhara_column_meta"] = [meta[k] for k in keep]
    return out


def fold_label_wrap_continuation_rows(df):
    """Fold stub-only wrap rows (no measures) into the previous data row.

    When PyMuPDF splits a Cause-of-Death cell across physical rows, the
    continuation has empty Sl.No./measures and only a label fragment.
    """
    import pandas as pd

    if df is None or getattr(df, "empty", True) or df.shape[0] < 2 or df.shape[1] < 3:
        return df

    n_cols = df.shape[1]
    _SNO_RE = re.compile(r"^(?:sl\.?\s*no\.?|s\.?\s*no\.?|serial(?:\s*no\.?)?|#)$", re.I)

    def _vals(i: int) -> List[str]:
        return [_cell_str(v) for v in df.iloc[:, i].tolist() if _cell_str(v)]

    def _looks_like_serial(i: int, vals: List[str]) -> bool:
        if _SNO_RE.match(str(df.columns[i] or "").strip()):
            return True
        ints = [int(v) for v in vals if re.fullmatch(r"\d{1,3}", v)]
        if len(ints) < max(3, int(len(vals) * 0.6)):
            return False
        return min(ints) >= 1 and max(ints) <= len(vals) + 5

    measure_idxs: List[int] = []
    label_idxs: List[int] = []
    sno_idxs: List[int] = []
    for i in range(n_cols):
        vals = _vals(i)
        if not vals:
            continue
        if _looks_like_serial(i, vals):
            sno_idxs.append(i)
            label_idxs.append(i)
            continue
        num = sum(1 for v in vals if _is_numeric_cell(v))
        if num >= max(1, int(len(vals) * 0.6)):
            measure_idxs.append(i)
        else:
            label_idxs.append(i)

    # Only treat columns left of the first measure block as stubs/labels.
    if measure_idxs:
        first_m = measure_idxs[0]
        label_idxs = [i for i in label_idxs if i < first_m]
        sno_idxs = [i for i in sno_idxs if i < first_m]

    if not measure_idxs or not label_idxs:
        return df

    name_col = max(
        (i for i in label_idxs if i not in sno_idxs),
        key=lambda i: (
            sum(len(_cell_str(v)) for v in df.iloc[:, i].tolist()),
            sum(1 for v in df.iloc[:, i].tolist() if _cell_str(v)),
        ),
        default=label_idxs[-1],
    )

    rows = df.values.tolist()
    out_rows: List[List[Any]] = []
    for row in rows:
        cur = list(row)
        name = _cell_str(cur[name_col])
        sno = any(_cell_str(cur[i]) for i in sno_idxs)
        has_meas = any(
            _cell_str(cur[i]) and _is_numeric_cell(_cell_str(cur[i]))
            for i in measure_idxs
        )
        if out_rows and name and not sno and not has_meas:
            prev = out_rows[-1]
            prev_name = _cell_str(prev[name_col])
            if _looks_like_name_continuation(name, prev=prev_name):
                prev[name_col] = _coalesce_split_cell_values(prev_name, name)
                for i in label_idxs:
                    if i == name_col:
                        continue
                    frag = _cell_str(cur[i])
                    if frag:
                        prev[i] = _coalesce_split_cell_values(prev[i], frag)
                continue
        out_rows.append(cur)

    out = pd.DataFrame(out_rows, columns=list(df.columns))
    for key, val in getattr(df, "attrs", {}).items():
        out.attrs[key] = val
    return out


def _cell_line_parts(v: Any) -> List[str]:
    raw = _cell_raw_text(v)
    if not raw.strip():
        return []
    lines = [ln.strip() for ln in raw.split("\n")]
    nonempty = [ln for ln in lines if ln]
    if nonempty:
        return nonempty
    return []


def _cell_looks_multivalue(v: Any, n: int) -> bool:
    if n < 2:
        return False
    parts = _cell_line_parts(v)
    if len(parts) >= 2:
        return True
    flat = _cell_str(v)
    if not flat:
        return False
    spaced = flat.split()
    if len(spaced) >= min(n, 2):
        return True
    compact = re.sub(r"\s+", "", flat)
    if re.fullmatch(r"\d+", compact) and len(compact) >= min(n, 2):
        return True
    return False


def _split_measure_cell_to_n(v: Any, n: int) -> List[Optional[str]]:
    """Split a numeric/age cell into n row values. Never cram overflow into the last row."""
    if n <= 0:
        return []
    parts = _cell_line_parts(v)
    if len(parts) == n:
        return parts
    flat = _cell_str(v)
    if not flat:
        return [None] * n
    spaced = flat.split()
    if len(spaced) == n:
        return spaced
    # Glued single-digit stacks only when separators existed before flatten.
    compact = re.sub(r"\s+", "", flat)
    if (
        re.fullmatch(r"\d+", compact)
        and len(compact) == n
        and len(spaced) > 1
    ):
        return list(compact)
    if len(parts) == 1:
        out: List[Optional[str]] = [None] * n
        out[0] = parts[0]
        return out
    if 1 < len(parts) < n:
        out = [None] * n
        for i, p in enumerate(parts):
            out[i] = p
        return out
    if len(parts) > n:
        # Keep the first n lines; do NOT join the rest into the last cell
        # (that was cramming later diseases' age counts into one row).
        return parts[:n]
    out = [None] * n
    out[0] = flat
    return out


def _consensus_numeric_line_count(
    row: Sequence[Any],
    n_cols: int,
    skip_cols: Optional[set] = None,
) -> int:
    """Median newline-count across columns that look like stacked numeric measures."""
    skip = skip_cols or set()
    counts: List[int] = []
    for c in range(min(len(row), n_cols)):
        if c in skip:
            continue
        parts = _cell_line_parts(row[c])
        if len(parts) < 2:
            continue
        numish = sum(1 for p in parts if _is_numeric_cell(p))
        if numish >= max(2, int(len(parts) * 0.6)):
            counts.append(len(parts))
    if not counts:
        return 0
    counts.sort()
    return counts[len(counts) // 2]


def _sex_values_for_n(
    cell: Any,
    n: int,
    sex_toks: Optional[List[str]],
) -> List[Optional[str]]:
    """Build a length-n Sex column, preserving blank lines between M/F when present."""
    if sex_toks and len(sex_toks) == n:
        return list(sex_toks)
    raw_lines = [ln.strip() for ln in _cell_raw_text(cell).split("\n")]
    if len(raw_lines) >= n:
        out: List[Optional[str]] = []
        for ln in raw_lines[:n]:
            out.append(_normalize_sex_token(ln) if ln else None)
        # If most lines decoded to M/F, fill isolated glue failures from neighbors.
        known = sum(1 for v in out if v in ("M", "F"))
        if known >= max(2, int(n * 0.75)):
            for i, v in enumerate(out):
                if v in ("M", "F"):
                    continue
                prev = out[i - 1] if i else None
                nxt = out[i + 1] if i + 1 < n else None
                if prev == "M" and (nxt in (None, "F", "M")):
                    out[i] = "F" if nxt != "F" else "M"
                elif prev == "F" and (nxt in (None, "M", "F")):
                    out[i] = "M" if nxt != "M" else "F"
                elif nxt == "F":
                    out[i] = "M"
                elif nxt == "M":
                    out[i] = "F"
        return out
    out = [None] * n
    if sex_toks:
        for i, tok in enumerate(sex_toks):
            if i < n:
                out[i] = tok
        return out
    single = _normalize_sex_token(_cell_str(cell))
    if single:
        out[0] = single
    return out


_ICD_IN_NAME_RE = re.compile(r"\([A-Za-z]?\d")
# Code-range tails: "B49 B65-B94 & B99)", "X10-X39, X50-X59)"
_CODE_TAIL_RE = re.compile(
    r"^[A-Z]?\d[\dA-Za-z,\-\s&/\)]*$"
)


def _looks_like_name_continuation(line: Any, prev: Any = None) -> bool:
    """True when a name line is a wrap/ICD tail, not a new disease title."""
    s = _cell_str(line)
    if not s:
        return True
    # Bare serials on an F row are almost always bleed from the next M row.
    if re.fullmatch(r"\d{1,4}", s):
        return False
    if s.startswith("(") or s.startswith("&") or s.startswith(","):
        return True
    if s[0].islower():
        return True
    # Pure ICD / code fragment without a wordy title.
    if re.match(r"^[\dA-Za-z,\-\s&/\(\)]+$", s) and not re.search(r"[A-Za-z]{5,}", s):
        return True
    # Code-range continuation lines (often after a truncated ICD paren).
    if _CODE_TAIL_RE.match(s) and ("-" in s or "&" in s or s.endswith(")")):
        return True

    prev_s = _cell_str(prev) if prev is not None else ""
    if prev_s:
        # Unclosed ICD / list on previous line — only absorb wrap-like tails,
        # never the next Capitalized disease title (common when ")" was clipped).
        if prev_s.count("(") > prev_s.count(")"):
            if (
                s[0].islower()
                or s.startswith("(")
                or s.startswith("&")
                or s.startswith(",")
                or (
                    _CODE_TAIL_RE.match(s)
                    and ("-" in s or "&" in s or s.endswith(")"))
                )
            ):
                return True
            return False
        if prev_s.rstrip().endswith((",", "-", "&", "/")):
            # Trailing list connector: wrap if next line is clearly a tail.
            if (
                s[0].islower()
                or s.startswith("(")
                or _CODE_TAIL_RE.match(s)
                or len(s.split()) <= 6
            ):
                return True
        # "… organs & miliary" / trailing connector → next line finishes the title.
        # Include "to/as/for/with/by/from/in" (Complication related to / Pregnancy)
        # and "elsewhere" (Others Not elsewhere / Classified).
        if re.search(
            r"(?:&\s*miliary|&|and|of|the|or|to|as|for|with|by|from|in|"
            r"elsewhere|presume[d]?|advers|not)\s*$",
            prev_s,
            re.I,
        ):
            # Avoid "… diseases (B55-B64)" matching bare "of" inside earlier words;
            # require the connector at the very end (already anchored) and a wrap-like next line.
            if s[0].islower() or s.startswith("(") or _CODE_TAIL_RE.match(s) or len(s) < 45:
                # Still reject a clear new title: Capitalized + own ICD already closed/open.
                new_title = (
                    s[0].isupper()
                    and len(s.split()) >= 3
                    and (
                        _ICD_IN_NAME_RE.search(s)
                        or re.match(r"^(?:All |Other |Total|INFECTIOUS|NEOPLASMS|Malignant)", s)
                    )
                )
                if not new_title:
                    return True
        # "such as Birth Injuries" wraps onto the next line when the extract drops
        # the trailing comma. Only absorb while the post-"such as" clause is short.
        such_m = re.search(r"\bsuch as\b(.*)$", prev_s, re.I)
        if such_m:
            after = such_m.group(1).strip().strip(",;/")
            if after and not after.endswith((".", ")")) and len(after.split()) <= 6:
                new_title = (
                    s[0].isupper()
                    and len(s.split()) >= 3
                    and (
                        _ICD_IN_NAME_RE.search(s)
                        or re.match(
                            r"^(?:All |Other |Total|INFECTIOUS|NEOPLASMS|Malignant)", s
                        )
                    )
                )
                if not new_title:
                    return True
        # Same lead word, ICD only on the second line:
        # "Tuberculosis of other organs & miliary" + "Tuberculosis (A18-A19"
        prev_first = re.split(r"\s+", prev_s, maxsplit=1)[0].lower().strip(",;")
        cur_first = re.split(r"\s+", s, maxsplit=1)[0].lower().strip(",;")
        if (
            len(prev_first) >= 5
            and prev_first == cur_first
            and _ICD_IN_NAME_RE.search(s)
            and not _ICD_IN_NAME_RE.search(prev_s)
        ):
            return True
    return False


def _assign_pair_label_parts(
    parts: List[str],
    sex_toks: List[str],
) -> List[Optional[str]]:
    """
    Map stacked label lines onto alternating M/F rows.

    Disease titles belong on M rows; F rows stay empty unless the line is a
    wrap/ICD continuation under the current pair. Never fill sequentially
    (that put the *next* disease title onto the previous F row).
    """
    n = len(sex_toks)
    out: List[Optional[str]] = [None] * n
    m_idxs = [i for i, t in enumerate(sex_toks) if t == "M"]
    f_idxs = [i for i, t in enumerate(sex_toks) if t == "F"]
    if not m_idxs:
        for i, p in enumerate(parts):
            if i < n:
                out[i] = p
        return out

    if len(parts) == n:
        return list(parts)
    if len(parts) <= len(m_idxs):
        for lab, mi in zip(parts, m_idxs):
            out[mi] = lab
        return out

    mi_i = 0
    fi_i = 0
    current_m: Optional[int] = None
    current_f: Optional[int] = None
    for part in parts:
        head = out[current_m] if current_m is not None else None
        # Also consider text already parked on the F wrap of this pair.
        if current_f is not None and out[current_f]:
            head = f"{head} {out[current_f]}".strip() if head else out[current_f]
        if current_m is not None and _looks_like_name_continuation(part, prev=head):
            target = current_f if current_f is not None else current_m
            prev = out[target]
            out[target] = f"{prev} {part}".strip() if prev else part
            continue
        if mi_i >= len(m_idxs):
            # Overflow titles — append to last F/M rather than shifting earlier rows.
            target = f_idxs[-1] if f_idxs else m_idxs[-1]
            prev = out[target]
            out[target] = f"{prev} {part}".strip() if prev else part
            continue
        current_m = m_idxs[mi_i]
        current_f = f_idxs[fi_i] if fi_i < len(f_idxs) else None
        mi_i += 1
        fi_i += 1
        out[current_m] = part
    return out


def _column_looks_like_stub_label(cell: Any, expected_rows: int) -> bool:
    """True when a stacked cell is a text stub/label (Cause of Death), not measures."""
    parts = _cell_line_parts(cell)
    if len(parts) < 2:
        flat = _cell_str(cell)
        if not flat:
            return False
        # Single prose blob with spaces but no newlines — still a label if not numeric.
        return not _is_numeric_cell(flat) and len(flat.split()) >= 2
    numish = sum(1 for p in parts if _is_numeric_cell(p))
    if numish >= max(2, int(len(parts) * 0.5)):
        return False
    # Extra wrap lines beyond the measure-row count are a strong label signal.
    if expected_rows >= 2 and len(parts) > expected_rows:
        return True
    return numish <= max(1, int(len(parts) * 0.25))


def _merge_score_for_label_groups(left: Sequence[str], right: Sequence[str]) -> float:
    """Lower score ⇒ prefer merging these adjacent label groups (wrap repair)."""
    prev = " ".join(left).strip()
    cur = right[0] if right else ""
    if not prev or not cur:
        return 0.0
    score = 0.0
    if _looks_like_name_continuation(cur, prev=prev):
        score -= 100.0
    if prev.rstrip().endswith((",", "-", "&", "/", "to", "and", "of", "the", "or", "as")):
        score -= 50.0
    if prev.lower().rstrip().endswith("elsewhere"):
        score -= 40.0
    if re.search(r"\bsuch as\b", prev, re.I):
        score -= 40.0
    # Short Capitalized tails ("Duodenum", "Pregnancy", "Classified") look like wraps.
    if len(cur.split()) <= 2 and cur[0].isupper():
        score -= 20.0
    # Two long standalone titles — avoid merging.
    if len(left[-1].split()) >= 2 and len(cur.split()) >= 2 and cur[0].isupper():
        if not _looks_like_name_continuation(cur, prev=prev):
            score += 35.0
    return score


def _assign_label_parts_to_n(parts: List[str], n: int) -> List[Optional[str]]:
    """Map stacked label lines onto n data rows, folding wrap continuations.

    PyMuPDF stacks Cause-of-Death wraps as extra newlines while S.No./measures
    stay one line per disease. Fold those wraps so labels align with measures.
    """
    if n <= 0:
        return []
    cleaned = [p for p in parts if _cell_str(p)]
    if not cleaned:
        return [None] * n
    if len(cleaned) == n:
        return list(cleaned)
    if len(cleaned) < n:
        out: List[Optional[str]] = [None] * n
        for i, p in enumerate(cleaned):
            out[i] = p
        return out

    # Phase 1: glue natural wrap/ICD continuations into groups.
    groups: List[List[str]] = [[cleaned[0]]]
    for part in cleaned[1:]:
        head = " ".join(groups[-1])
        if _looks_like_name_continuation(part, prev=head):
            groups[-1].append(part)
        else:
            groups.append([part])

    # Phase 2: if still too many groups, merge adjacent ones with best wrap score.
    while len(groups) > n:
        best_i = 0
        best_score = float("inf")
        for i in range(len(groups) - 1):
            sc = _merge_score_for_label_groups(groups[i], groups[i + 1])
            if sc < best_score:
                best_score = sc
                best_i = i
        groups[best_i] = groups[best_i] + groups[best_i + 1]
        del groups[best_i + 1]

    out = [" ".join(g).strip() for g in groups[:n]]
    # If phase-1 under-grouped (rare), pad.
    while len(out) < n:
        out.append(None)
    return out  # type: ignore[return-value]


def _split_label_cell_to_sex_rows(v: Any, sex_toks: List[str]) -> List[Optional[str]]:
    """Place S.No. / disease labels onto expanded M/F rows.

    Short labels often appear once per M/F pair (on the M line). Long disease
    names may wrap onto the F line — keep those lines on their row index.
    """
    n = len(sex_toks)
    parts = _cell_line_parts(v)
    out: List[Optional[str]] = [None] * n
    m_idxs = [i for i, t in enumerate(sex_toks) if t == "M"]
    pair_aligned = (
        bool(m_idxs)
        and n == 2 * len(m_idxs)
        and all(sex_toks[i] == "F" for i in range(1, n, 2))
    )

    def _place_pair_digits(compact: str) -> Optional[List[Optional[str]]]:
        if not (pair_aligned and re.fullmatch(r"\d+", compact) and len(compact) == len(m_idxs)):
            return None
        placed: List[Optional[str]] = [None] * n
        for digit, mi in zip(compact, m_idxs):
            placed[mi] = digit
        return placed

    if not parts:
        flat = _cell_str(v)
        if not flat:
            return out
        compact = re.sub(r"\s+", "", flat)
        placed = _place_pair_digits(compact)
        if placed is not None:
            return placed
        if re.fullmatch(r"\d+", compact) and len(compact) == n:
            return list(compact)
        spaced = flat.split()
        if len(spaced) == n:
            return spaced
        if pair_aligned and len(spaced) == len(m_idxs):
            for lab, mi in zip(spaced, m_idxs):
                out[mi] = lab
            return out
        out[0] = flat
        return out

    if len(parts) == 1:
        placed = _place_pair_digits(re.sub(r"\s+", "", parts[0]))
        if placed is not None:
            return placed

    if pair_aligned:
        return _assign_pair_label_parts(parts, sex_toks)

    if len(parts) == n:
        return parts
    if len(parts) == len(m_idxs) and m_idxs:
        for lab, mi in zip(parts, m_idxs):
            out[mi] = lab
        return out
    for i, p in enumerate(parts):
        if i < n:
            out[i] = p
    return out


def _split_label_cell_to_n(
    v: Any,
    n: int,
    sex_vals: Sequence[Optional[str]],
) -> List[Optional[str]]:
    """Place stub/name labels onto n expanded rows (pair-aware when M/F alternates)."""
    if len(sex_vals) == n and all(t in ("M", "F") for t in sex_vals):
        return _split_label_cell_to_sex_rows(v, list(sex_vals))

    parts = _cell_line_parts(v)
    out: List[Optional[str]] = [None] * n
    if not parts:
        flat = _cell_str(v)
        if flat:
            out[0] = flat
        return out
    m_idxs = [i for i, t in enumerate(sex_vals) if t == "M"]
    if m_idxs and len(parts) <= len(m_idxs):
        for lab, mi in zip(parts, m_idxs):
            out[mi] = lab
        return out
    if len(parts) != n:
        return _assign_label_parts_to_n(parts, n)
    return list(parts)


def repair_sex_pair_next_row_label_bleed(
    rows: List[List[Any]],
    sex_col: Optional[int],
) -> List[List[Any]]:
    """
    Move disease titles that landed on an F row back onto the following M row.

    Empty leading stubs on F rows must stay empty. When the next disease title
    was pulled up into that hole, the following M row keeps only a wrap/ICD
    fragment — push the title down and clear the F stub.
    """
    if sex_col is None or sex_col < 1 or not rows:
        return rows
    out = [_pad_row(r, max(len(x) for x in rows)) for r in rows]
    for i in range(len(out) - 1):
        if _cell_str(out[i][sex_col]).upper() != "F":
            continue
        if _cell_str(out[i + 1][sex_col]).upper() != "M":
            continue
        if i > 0 and _cell_str(out[i - 1][sex_col]).upper() != "M":
            # Only repair classic M / F / M sequences.
            continue
        for c in range(sex_col):
            cur = _cell_str(out[i][c])
            if not cur:
                continue
            # Legitimate wrap under the previous M — leave it.
            if _looks_like_name_continuation(cur):
                continue
            nxt = _cell_str(out[i + 1][c])
            if nxt and not _looks_like_name_continuation(nxt):
                # Next M already has its own full title — don't steal.
                continue
            # F holds the next disease title; next M is empty or ICD/wrap only.
            if nxt:
                out[i + 1][c] = f"{cur} {nxt}".strip()
            else:
                out[i + 1][c] = cur
            out[i][c] = None
    return out


def _row_max_measure_line_count(
    row: Sequence[Any],
    n_cols: int,
    sex_col: int,
) -> int:
    """Max newline/part count across measure columns (right of Sex)."""
    best = 0
    for c in range(sex_col + 1, n_cols):
        if c >= len(row):
            break
        parts = _cell_line_parts(row[c])
        if parts:
            best = max(best, len(parts))
            continue
        flat = _cell_str(row[c])
        if flat and _is_numeric_cell(flat):
            best = max(best, 1)
    return best


def _join_stacked_cell_values(a: Any, b: Any) -> Optional[str]:
    """Concatenate two cells' line parts (first-row head + continuation stack)."""
    parts = _cell_line_parts(a) + _cell_line_parts(b)
    if parts:
        return "\n".join(parts)
    sa, sb = _cell_str(a), _cell_str(b)
    if sa and sb:
        return f"{sa}\n{sb}"
    return sa or sb or None


def _leading_stub_cols_empty(row: Sequence[Any], sex_col: int) -> bool:
    for c in range(min(sex_col, len(row))):
        if _cell_str(row[c]):
            return False
    return True


def _merge_measure_continuation_rows(
    rows: List[List[Any]],
    n_cols: int,
    sex_col: Optional[int],
) -> List[List[Any]]:
    """
    Merge a label+Sex stack row with the following measure-only continuation.

    PyMuPDF often emits cause-of-death blocks as two physical rows:
      (1) S.No./Name/Sex stacked for many M/F pairs, but age cells hold only
          the first pair's values;
      (2) empty stubs/Sex, with the remaining age counts stacked as newlines.

    Expanding those independently leaves hollow M/F rows then an orphan
    numeric block. Fold (2)'s measures into (1) before splitting.
    """
    if sex_col is None or not rows:
        return rows
    out: List[List[Any]] = []
    i = 0
    while i < len(rows):
        row = _pad_row(rows[i], n_cols)
        sex_toks = _sex_tokens_from_cell(row[sex_col])
        sex_n = len(sex_toks) if sex_toks else 0
        meas_n = _row_max_measure_line_count(row, n_cols, sex_col)

        if sex_n >= 2 and meas_n < sex_n and i + 1 < len(rows):
            nxt = _pad_row(rows[i + 1], n_cols)
            nxt_sex_toks = _sex_tokens_from_cell(nxt[sex_col])
            nxt_sex_n = len(nxt_sex_toks) if nxt_sex_toks else 0
            nxt_meas = _row_max_measure_line_count(nxt, n_cols, sex_col)
            sex_blank = not _cell_str(nxt[sex_col])
            combined = meas_n + nxt_meas
            # Continuation: stacked numerics, empty identity stubs, little/no Sex.
            if (
                nxt_meas >= 2
                and _leading_stub_cols_empty(nxt, sex_col)
                and (sex_blank or nxt_sex_n < 2)
                and combined >= max(2, sex_n - 2)
                and combined <= sex_n + 2
            ):
                for c in range(sex_col + 1, n_cols):
                    row[c] = _join_stacked_cell_values(row[c], nxt[c])
                out.append(row)
                i += 2
                continue

        out.append(row)
        i += 1
    return out


def expand_collapsed_sex_pair_rows(rows: List[List[Any]]) -> List[List[Any]]:
    """
    Expand pymupdf rows that collapsed multiple logical lines into one cell.

    Cause-of-death / sex-by-age tables often omit hard rules between Male/Female
    (or between successive diseases), so find_tables() returns one physical row
    with stacked ``M\\nF\\n…`` and/or stacked age counts. Split those back into
    one output row per stacked measure line.

    Row count is driven by the *consensus numeric line count* across measure
    columns (not Sex alone), so a lone ``F`` above ten age lines still expands,
    and leftover measure lines are never joined into the last row.
    """
    if not rows:
        return rows
    n_cols = max((len(r) for r in rows), default=0)
    if n_cols < 3:
        return rows
    padded = [_pad_row(r, n_cols) for r in rows]
    sex_col = _find_sex_column(padded, n_cols)
    # Fold measure-only continuation rows into the preceding Sex stack first.
    padded = _merge_measure_continuation_rows(padded, n_cols, sex_col)

    out: List[List[Any]] = []
    for row in padded:
        skip = {sex_col} if sex_col is not None else set()
        measure_n = _consensus_numeric_line_count(row, n_cols, skip)
        sex_toks = _sex_tokens_from_cell(row[sex_col]) if sex_col is not None else None
        sex_n = len(sex_toks) if sex_toks else 0
        n = max(measure_n, sex_n)
        if n < 2:
            out.append(row)
            continue
        # Require stacked numeric evidence (avoid splitting on Sex alone).
        if measure_n < 2 and sex_n < 2:
            out.append(row)
            continue
        if measure_n < 2:
            # Sex stack without matching measures — only expand when other
            # columns also look multi-valued at sex_n.
            other_multi = sum(
                1
                for c in range(n_cols)
                if c != sex_col and _cell_looks_multivalue(row[c], sex_n)
            )
            if other_multi < 1:
                out.append(row)
                continue
            n = sex_n

        sex_vals: List[Optional[str]]
        if sex_col is not None:
            sex_vals = _sex_values_for_n(row[sex_col], n, sex_toks)
        else:
            sex_vals = [None] * n

        split_cols: List[List[Optional[str]]] = []
        for c in range(n_cols):
            if sex_col is not None and c == sex_col:
                split_cols.append(list(sex_vals))
                continue
            if sex_col is not None and c < sex_col:
                split_cols.append(_split_label_cell_to_n(row[c], n, sex_vals))
                continue
            # No Sex column (region×Male/Female headers): still fold Cause-of-
            # Death wraps so labels align with the measure-row count.
            if sex_col is None and _column_looks_like_stub_label(row[c], n):
                parts = _cell_line_parts(row[c])
                if not parts:
                    flat = _cell_str(row[c])
                    parts = [flat] if flat else []
                split_cols.append(_assign_label_parts_to_n(parts, n))
                continue
            split_cols.append(_split_measure_cell_to_n(row[c], n))

        for i in range(n):
            out.append([split_cols[c][i] for c in range(n_cols)])
    return repair_sex_pair_next_row_label_bleed(out, sex_col)


def dataframe_from_extracted_rows(rows: Optional[List[List[Any]]]):
    """
    Build a pandas DataFrame from a pymupdf `tab.extract()` grid, flattening
    multi-row / merged headers when present.

    Hierarchy is stored on ``df.attrs["dhara_column_meta"]`` as
    ``[{"name", "header_group", "header_path"}, ...]`` for Preview.
    """
    import pandas as pd

    if not rows:
        return pd.DataFrame()

    n_cols = max((len(r) for r in rows), default=0)
    if n_cols == 0:
        return pd.DataFrame()

    # Expand collapsed M/F stacks while newlines still exist; then unglue
    # horizontally packed measure values into neighbouring empty columns.
    padded = expand_collapsed_sex_pair_rows([_pad_row(r, n_cols) for r in rows])
    n_cols = max((len(r) for r in padded), default=n_cols)
    sex_col = _find_sex_column(padded, n_cols)
    # Also repair already-separate rows where a next-disease title bled into
    # the empty F stub (common with wrapped Name cells).
    padded = repair_sex_pair_next_row_label_bleed(padded, sex_col)
    padded = repair_glued_numeric_cells([_pad_row(r, n_cols) for r in padded])
    header_count, skip_rows = detect_header_rows(padded, n_cols)

    root = None
    for i in range(header_count):
        if i not in skip_rows and not _blank(padded[i]):
            root = padded[i]
            break

    # Pull any remaining subheader strips that follow the detected block.
    while True:
        next_i = header_count
        while next_i < len(padded) and next_i in skip_rows:
            next_i += 1
        if next_i >= len(padded):
            break
        if root is not None:
            leaf_part, data_part = _split_hybrid_leaf_data_row(padded[next_i], root, n_cols)
            if leaf_part is not None and data_part is not None:
                padded[next_i] = leaf_part
                padded.insert(next_i + 1, data_part)
                header_count = next_i + 1
                break
        if _row_looks_like_data(padded[next_i], root):
            break
        if _row_is_subheader(padded[next_i], root) or _row_is_text_header(
            padded[next_i], continuation=True, parent_row=root
        ):
            header_count = next_i + 1
            continue
        break

    header_matrix = [padded[i] for i in range(header_count) if i not in skip_rows]
    if not header_matrix:
        header_matrix = [padded[0]]
        header_count = 1

    resolved = resolve_column_headers(header_matrix, n_cols)
    leaf_names = _uniquify_columns([c["name"] for c in resolved])
    column_meta = []
    for i in range(n_cols):
        path = [str(p) for p in (resolved[i].get("header_path") or []) if str(p).strip()]
        if not path:
            path = [resolved[i].get("name") or leaf_names[i]]
        # Keep original leaf labels in header_path for display (S.R.S. under
        # Birth Rate vs Death Rate). DataFrame column names stay uniquified.
        column_meta.append({
            "name": leaf_names[i],
            "header_group": path[-2] if len(path) >= 2 else None,
            "header_path": path,
        })

    body = [
        padded[i]
        for i in range(header_count, len(padded))
        if i not in skip_rows and not _blank(padded[i])
    ]
    # Index strips (1..N / (1)(2)(3)) are skipped for header naming but must
    # remain visible as the first body row(s) when they sit under the headers.
    leading_index: List[List[Any]] = []
    for i in range(header_count, len(padded)):
        if i not in skip_rows:
            break
        if _blank(padded[i]):
            continue
        if _row_is_column_number_strip(padded[i], n_cols):
            leading_index.append(padded[i])
        else:
            # Non-index skip (banner) — stop; don't pull mid-table strips forward.
            break
    if leading_index:
        body = leading_index + body
    caption = extract_in_grid_caption(padded)

    def _attach_caption_attrs(frame):
        frame.attrs["dhara_column_meta"] = column_meta
        if caption.get("title"):
            frame.attrs["dhara_table_caption"] = caption["title"]
        if caption.get("table_id_label"):
            frame.attrs["dhara_banner_table_id"] = caption["table_id_label"]
        return frame

    if not body:
        df = pd.DataFrame(columns=leaf_names)
        return _attach_caption_attrs(df)

    clean_body: List[List[Any]] = [
        [_cell_str(v) or None for v in row] for row in body
    ]
    df = pd.DataFrame(clean_body, columns=leaf_names)
    df = _attach_caption_attrs(df)
    # Collapse PyMuPDF interstitial phantom columns (Cause/(2)/(3), Male/(2)/(3))
    # and fold stub-only wrap rows into the parent disease row.
    df = coalesce_phantom_grid_columns(df)
    df = fold_label_wrap_continuation_rows(df)
    return df
