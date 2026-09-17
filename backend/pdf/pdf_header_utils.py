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
    s = str(v).replace("\n", " ").strip()
    return re.sub(r"\s+", " ", s)


def _is_numeric_cell(v: Any) -> bool:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return True
    s = _cell_str(v).replace(",", "").replace("*", "").strip()
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
    s = _cell_str(v).replace(",", "").replace("*", "").strip()
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
    # Multi-decimal measurements (150.54) are data; plain small ints are codes.
    s = _cell_str(v).replace(",", "").strip()
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
        """Consecutive descriptive banners starting at ``start`` (label index)."""
        run: List[Tuple[int, str]] = []
        for pair in banners[start:]:
            _idx, b = pair
            if _is_table_id_only(b) or _UNIT_GROUP_RE.match(b):
                break
            if _is_descriptive_in_grid_title(b):
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
            # Prefer a short primary caption. Do not swallow column-list banners
            # (e.g. "Scheme name, beneficiaries, budget") into the title — those
            # must remain in the body so headers/data extract correctly.
            kept: List[Tuple[int, str]] = []
            for i, pair in enumerate(title_pairs):
                _idx, lab = pair
                if i > 0:
                    if _looks_like_column_list_banner(lab):
                        break
                    if len(lab) > 48 or lab.count(",") >= 2:
                        break
                    if kept:
                        # At most one short genuine subtitle (e.g. URBAN).
                        kept.append(pair)
                        break
                kept.append(pair)
            if kept:
                out["title"] = " — ".join(lab for _i, lab in kept)
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
    """
    scan = body[: max(_MAX_HEADER_ROWS + 2, 10)]
    skip_rows: List[int] = []
    for i, row in enumerate(scan):
        if _row_is_full_width_banner(row):
            skip_rows.append(i)
            continue
        non_empty = [v for v in row if _cell_str(v)]
        if not non_empty:
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

    padded = repair_glued_numeric_cells([_pad_row(r, n_cols) for r in rows])
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
    return _attach_caption_attrs(df)
