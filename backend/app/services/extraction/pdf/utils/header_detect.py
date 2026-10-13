"""Multi-row header detection, resolution, and flattening."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

from app.services.extraction.pdf.utils.caption import (
    _BARE_INDEX_RE,
    _COL_NUM_RE,
    _LEAF_MAX_LEN,
    _TABLE_BANNER_RE,
    _blank,
    _cell_str,
    _is_leaf_header_token,
    _is_measurement_number,
    _is_numeric_cell,
    _is_year_code,
    _pad_row,
    _row_is_full_width_banner,
)

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
    return _recover_colspan_leaf_names(out, kinds)

def _default_order_leaf_labels(n: int) -> List[str]:
    """Synthetic 1..8, >8, All… labels when a spanning group has no leaf row."""
    if n <= 0:
        return []
    base = [str(i) for i in range(1, 9)] + [">8"]
    if n <= len(base):
        return base[:n]
    extra = ["All"] + [str(i) for i in range(10, n + 1)]
    return base + extra[: n - len(base)]

_COLSPAN_LEAF_GROUP_RE = re.compile(
    r"(?i)\b("
    r"birth\s*order|order|education|sex|gender|religion|"
    r"marital|literacy|qualification|occupation"
    r")\b"
)

def _recover_colspan_leaf_names(
    resolved: List[dict],
    kinds: List[str],
) -> List[dict]:
    """Assign leaf codes under a colspan group that lost its 1/2/3…/>8 row.

    PyMuPDF sometimes drops the birth-order leaf strip while keeping the parent
    ``BIRTH ORDER`` / education banner. Horizontal fill then repeats that parent
    as every leaf name; ``coalesce_phantom_grid_columns`` would glue the measure
    values into one cell. Recover positional leaves so columns stay distinct.

    Does NOT touch long prose group labels (Cause of Death, indicator names) —
    those empty slots are phantom splits and must still coalesce.
    """
    if not resolved or not kinds or len(kinds) != len(resolved):
        return resolved
    out = [dict(c) for c in resolved]
    n = len(out)
    i = 0
    while i < n:
        if (kinds[i] if i < len(kinds) else "stub") != "group":
            i += 1
            continue
        j = i + 1
        while j < n and (kinds[j] if j < len(kinds) else "span") == "span":
            j += 1
        run = list(range(i, j))
        if len(run) < 2:
            i = j
            continue
        paths = [list(out[k].get("header_path") or []) for k in run]
        # Only recover when every column is a single identical label (no real leaves).
        if not all(len(p) == 1 for p in paths):
            i = j
            continue
        if len({p[0].strip().upper() for p in paths if p and p[0].strip()}) != 1:
            i = j
            continue
        group_name = paths[0][0].strip()
        # Skip stub-like tokens and long prose (Cause of Death & ICD-…).
        if len(group_name) < 8 and " " not in group_name:
            i = j
            continue
        if len(group_name) > 48 or not _COLSPAN_LEAF_GROUP_RE.search(group_name):
            i = j
            continue
        leaves = _default_order_leaf_labels(len(run))
        for k, leaf in zip(run, leaves):
            out[k] = {
                "name": leaf,
                "header_group": group_name,
                "header_path": [group_name, leaf],
            }
        i = j
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
    """Ensure DataFrame column labels are unique (append ' (2)', ' (3)', …)."""
    seen: Dict[str, int] = {}
    out: List[str] = []
    for raw in names:
        base = str(raw or "").strip() or "Col"
        n = seen.get(base, 0) + 1
        seen[base] = n
        out.append(base if n == 1 else f"{base} ({n})")
    return out

def _fill_blank_leading_serial_header(
    leaf_names: List[str],
    column_meta: List[dict],
) -> Tuple[List[str], List[dict]]:
    """Name a blank leading stub ``S.No.`` for cause-of-death style grids.

    PyMuPDF often leaves the serial column header empty (label sits outside the
    ruled box) while ``Name of the Disease`` / ``Sex`` are present — that becomes
    ``Col_1`` and routes the page to LLM. Filling the obvious serial label keeps
    cell values unchanged and allows auto-accept.
    """
    if not leaf_names:
        return leaf_names, column_meta
    first = str(leaf_names[0] or "").strip()
    if first and not re.match(r"^Col_\d+$", first, re.I):
        return leaf_names, column_meta
    second = str(leaf_names[1] if len(leaf_names) > 1 else "").strip().lower()
    third = str(leaf_names[2] if len(leaf_names) > 2 else "").strip().lower()
    disease_name = any(
        tip in second
        for tip in (
            "name of the disease",
            "name of disease",
            "cause of death",
        )
    )
    sex_layout = third in {"sex", "gender"} and (
        disease_name or "disease" in second or second.startswith("name")
    )
    if not (disease_name or sex_layout):
        return leaf_names, column_meta
    names = list(leaf_names)
    names[0] = "S.No."
    meta = list(column_meta) if column_meta else []
    if meta and len(meta) == len(names):
        meta[0] = {
            **meta[0],
            "name": "S.No.",
            "header_group": None,
            "header_path": ["S.No."],
        }
    return names, meta

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

__all__ = [
    "_fill_blank_leading_serial_header",
    "detect_header_rows",
    "flatten_headers",
    "resolve_column_headers",
]
