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
    if len(cells) < 3:
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
    if len(non_empty) >= max(3, int(len(cells) * 0.6)):
        return bool(_TABLE_BANNER_RE.match(label)) or len(label) >= 28
    return bool(_TABLE_BANNER_RE.match(label)) and len(non_empty) >= len(cells) * 0.5


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

    padded = [_pad_row(r, n_cols) for r in rows]
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
    if not body:
        df = pd.DataFrame(columns=leaf_names)
        df.attrs["dhara_column_meta"] = column_meta
        return df

    clean_body: List[List[Any]] = [
        [_cell_str(v) or None for v in row] for row in body
    ]
    df = pd.DataFrame(clean_body, columns=leaf_names)
    df.attrs["dhara_column_meta"] = column_meta
    return df
