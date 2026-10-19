"""Multi-row header detection, resolution, and flattening."""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

from app.services.extraction.pdf.utils.caption import (
    _COL_NUM_RE,
    _LEAF_MAX_LEN,
    _TABLE_BANNER_RE,
    _UNIT_GROUP_RE,
    _blank,
    _cell_str,
    _is_descriptive_in_grid_title,
    _is_leaf_header_token,
    _is_measurement_number,
    _is_numeric_cell,
    _is_table_id_only,
    _is_year_code,
    _looks_like_column_list_banner,
    _pad_row,
    _row_banner_label,
    _row_is_column_number_strip,
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

def _row_is_header_metadata_strip(row: Sequence[Any]) -> bool:
    """True when every non-empty cell is Name of Crop / Season / Appendix metadata."""
    labels = [_cell_str(v) for v in row if _cell_str(v)]
    return bool(labels) and all(_is_header_metadata_label(lab) for lab in labels)


def _row_is_column_title_banner(row: Sequence[Any]) -> bool:
    """Lone District / Sl.No row parked under a multi-level header — keep in resolve."""
    if not _row_is_full_width_banner(row):
        return False
    label = _row_banner_label(row) or ""
    return bool(_COLUMN_TITLE_LABEL_RE.match(label.strip()))


def resolve_column_headers(header_matrix: List[List[Any]], n_cols: int) -> List[dict]:
    """
    Resolve multi-row headers into a full top→leaf path per column.

    Each result:
      name          – leaf label (last path element)
      header_group  – immediate parent (compat; None if single-level)
      header_path   – full hierarchy ["L1", "L2", …, leaf] (length 1..N)
    """
    # Keep lone column-title banners (District). Drop caption / section banners.
    rows_in = [
        r
        for r in header_matrix
        if (not _row_is_full_width_banner(r)) or _row_is_column_title_banner(r)
    ]
    if not rows_in:
        rows_in = list(header_matrix)

    # Prefer a structural parent row over crop/season/appendix metadata strips.
    raw_top = _pad_row(rows_in[0], n_cols) if rows_in else []
    for r in rows_in:
        if not _row_is_header_metadata_strip(r) and not _row_is_column_title_banner(r):
            raw_top = _pad_row(r, n_cols)
            break
    kinds = _parent_col_kinds(raw_top) if rows_in else []

    rows = _fill_header_matrix(rows_in, n_cols)
    if not rows:
        # Empty headers stay blank — never invent Col_1 / Col_2 labels.
        return [
            {"name": "", "header_group": None, "header_path": [""]}
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
            if _is_header_metadata_label(lab):
                continue
            if path and path[-1].upper() == lab.upper():
                continue
            path.append(lab)

        if not path:
            path = [""]

        kind = kinds[i] if i < len(kinds) else "stub"
        # Sl.No left-fill into a District column yields two identity titles — keep the deepest.
        title_idxs = [
            j for j, p in enumerate(path) if _COLUMN_TITLE_LABEL_RE.match(p.strip())
        ]
        if len(title_idxs) >= 2:
            path = [path[title_idxs[-1]]]
        # Identity/stub columns must stay single-level even if a leaf token spilled under them.
        elif kind == "stub" and len(path) > 1 and path[0].upper() != path[-1].upper():
            # Prefer a later column-title leaf (District parked under a Sl.No rowspan).
            if _COLUMN_TITLE_LABEL_RE.match(path[-1].strip()):
                path = [path[-1]]
            else:
                path = [path[0]]

        name = path[-1]
        group = path[-2] if len(path) >= 2 else None
        out.append({"name": name, "header_group": group, "header_path": path})
    out = _recover_colspan_leaf_names(out, kinds)
    return _repair_irrigation_stack_header_paths(out)

def _repair_irrigation_stack_header_paths(resolved: List[dict]) -> List[dict]:
    """Attach orphan Exp/Productivity/Area/Error/Production leaves to Irrigated stacks.

    PyMuPDF often parks ``Season`` / ``Appendix`` metadata so the 5th leaf under
    Irrigated / Un Irrigated / Total loses its parent. Forward-fill the active
    stack group across consecutive measure leaves (max 5 per group).
    """
    if not resolved:
        return resolved
    out = [dict(c) for c in resolved]
    last_group: Optional[str] = None
    stack_count = 0
    for i, col in enumerate(out):
        path = [str(p) for p in (col.get("header_path") or []) if str(p).strip()]
        if not path:
            path = [str(col.get("name") or "")]
        leaf = path[-1]
        group_labels = [
            _normalize_irrigation_stack_group(p)
            for p in path[:-1]
            if _IRRIGATION_STACK_GROUP_RE.match(p)
        ]
        if group_labels:
            last_group = group_labels[-1]
            stack_count = 1 if _is_irrigation_stack_leaf(leaf) else 0
            # Drop non-stack parents; keep Irrigated|Un Irrigated|Total + leaf.
            if _is_irrigation_stack_leaf(leaf):
                path = [last_group, leaf]
            else:
                path = [p for p in path if not _is_header_metadata_label(p)]
                if not path:
                    path = [leaf]
            out[i] = {
                "name": path[-1],
                "header_group": path[-2] if len(path) >= 2 else None,
                "header_path": path,
            }
            continue

        if (
            _is_irrigation_stack_leaf(leaf)
            and last_group
            and stack_count > 0
            and stack_count < 5
        ):
            path = [last_group, leaf]
            stack_count += 1
            out[i] = {
                "name": leaf,
                "header_group": last_group,
                "header_path": path,
            }
            continue

        # Stub / non-stack column — reset so the next Irrigated block starts clean.
        if not _is_irrigation_stack_leaf(leaf):
            last_group = None
            stack_count = 0
        path = [p for p in path if not _is_header_metadata_label(p)]
        if not path:
            path = [leaf]
        out[i] = {
            "name": path[-1],
            "header_group": path[-2] if len(path) >= 2 else None,
            "header_path": path,
        }
    return out


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

def _is_caption_banner_label(label: str) -> bool:
    """Table id, title, unit, or column-list banners — not in-body section rows."""
    s = _cell_str(label)
    if not s:
        return False
    if _is_table_id_only(s) or _TABLE_BANNER_RE.match(s):
        return True
    if _UNIT_GROUP_RE.match(s):
        return True
    if _is_descriptive_in_grid_title(s):
        return True
    if _looks_like_column_list_banner(s):
        return True
    return False


# Crop / season / appendix strips parked in the header grid — metadata, not
# column parents (otherwise Preview shows "NAME OF CROP: PADDY" as L1).
_HEADER_METADATA_LABEL_RE = re.compile(
    r"(?i)^\s*(?:"
    r"name\s+of\s+crop\b|"
    r"season\s*:?-?|"
    r"appendix\s*:?"
    r")"
)

# Lone "District" / "Sl.No" under the header is a column title, not a body band.
_COLUMN_TITLE_LABEL_RE = re.compile(
    r"(?i)^\s*(?:"
    r"sl\.?\s*no\.?|s\.?\s*no\.?|sno|"
    r"district|name\s+of\s+(?:the\s+)?(?:district|block|state|panchayat)|"
    r"block|state|particulars|indicator|crop"
    r")\s*$"
)

_IRRIGATION_STACK_GROUP_RE = re.compile(
    r"(?i)^\s*(?:un\s*-?\s*)?irrigated\s*$|^\s*total\s*$"
)
_IRRIGATION_STACK_LEAF_RE = re.compile(
    r"(?i)(?:"
    r"no\.?\s*of\s*exp|"
    r"productivity|"
    r"area\s*\(|"
    r"sampling\s*error|"
    r"production\s+of\s+rice"
    r")"
)


def _is_header_metadata_label(label: str) -> bool:
    """True for Name of Crop / Season / Appendix cells — keep out of header_path."""
    return bool(_HEADER_METADATA_LABEL_RE.match(_cell_str(label)))


def _normalize_irrigation_stack_group(label: str) -> str:
    u = re.sub(r"\s+", " ", _cell_str(label).lower()).strip()
    if u in {"un irrigated", "un-irrigated", "unirrigated"}:
        return "Un Irrigated"
    if u == "irrigated":
        return "Irrigated"
    if u == "total":
        return "Total"
    return _cell_str(label)


def _is_irrigation_stack_leaf(label: str) -> bool:
    return bool(_IRRIGATION_STACK_LEAF_RE.search(_cell_str(label)))


def _row_is_section_label(row: Sequence[Any]) -> bool:
    """Single label across an otherwise empty row (district, block group, …).

    These sit in the body under the column headers. They are not captions and
    must not be dropped or promoted into the header block.

    Exception: bare column titles (``District``, ``Sl.No``) that PyMuPDF parks
    on their own row under a multi-level header — those belong in the header.
    Lowercase wrap continuations (``conducted due to``) are also header text.
    """
    if not _row_is_full_width_banner(row):
        return False
    label = _row_banner_label(row) or ""
    if _COLUMN_TITLE_LABEL_RE.match(label.strip()):
        return False
    if label and label[0].islower():
        return False
    return not _is_caption_banner_label(label)


def detect_header_rows(body: List[List[Any]], n_cols: int) -> Tuple[int, List[int]]:
    """Leading header-row count plus indices of banner / '(1)(2)(3)' rows to skip.

    Absorbs an arbitrary number of header levels (1..N) until a data row appears.
    Index-strip skips apply only before the first body-data row so blank-stub
    percentage rows like ``("", "(10.6)", "(13.6)", …)`` are never discarded.
    """
    scan = body[: max(_MAX_HEADER_ROWS + 2, 10)]
    skip_rows: List[int] = []
    seen_data = False
    seen_structure = False
    for i, row in enumerate(scan):
        if _row_is_full_width_banner(row):
            label = _row_banner_label(row) or ""
            # Leading captions are skipped. A single label after the header
            # (e.g. THIRUVANANTHAPURAM) is a section row and stays in the body.
            if not seen_data and (not seen_structure or _is_caption_banner_label(label)):
                skip_rows.append(i)
            continue
        non_empty = [v for v in row if _cell_str(v)]
        if not non_empty:
            continue
        seen_structure = True
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
        # Pure 1,2,3,…,N index row (allows one blank hole — PyMuPDF often
        # drops the Planned "3" under vertical headers).
        if _row_is_column_number_strip(row, n_cols):
            skip_rows.append(i)

    header_count = 0
    root_header_row: Optional[Sequence[Any]] = None
    levels = 0
    for i, row in enumerate(scan):
        if i in skip_rows:
            continue
        if _blank(row):
            break
        # District / group bands are body rows, never another header level.
        if _row_is_section_label(row):
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
            # Crop/season/appendix strips are header rows but make a bad parent
            # for stub/data classification (first district row looks like a leaf).
            if root_header_row is None and not _row_is_header_metadata_strip(row):
                root_header_row = row
            levels += 1
            continue

        if header_count > 0 and _row_is_subheader(row, root_header_row):
            header_count = i + 1
            if root_header_row is None and not _row_is_header_metadata_strip(row):
                root_header_row = row
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

def _is_explicit_empty_header_cell(v: Any) -> bool:
    """True for intentional blank header cells (``''``), not merge holes (``None``).

    PyMuPDF uses ``None`` for colspan/rowspan continuations and ``''`` when a
    bordered cell is present but empty (e.g. the blank stub between Particulars
    and the first year group). Only ``None`` may be filled from a neighbour.
    """
    return isinstance(v, str) and not str(v).strip()


def _fill_header_matrix(header_matrix: List[List[Any]], n_cols: int) -> List[List[str]]:
    """
    Resolve rowspan then colspan empties inside the header block.

    Vertical first (rowspan stubs), then horizontal (colspan group banners).
    Crop/season/appendix metadata is kept in-place but not propagated into
    empty cells — otherwise Appendix blocks Irrigated / rejected-due-to groups
    from filling across their leaf columns.

    Explicit blank cells (``''``) are never filled — they are real empty title
    cells, not merge continuations. ``None`` still receives rowspan/colspan fill.
    """
    rows: List[List[Any]] = [_pad_row(r, n_cols) for r in header_matrix]
    explicit_empty = [
        [_is_explicit_empty_header_cell(rows[r][c]) for c in range(n_cols)]
        for r in range(len(rows))
    ]
    for c in range(n_cols):
        last = ""
        for r in range(len(rows)):
            if explicit_empty[r][c]:
                rows[r][c] = ""
                # Do not carry a label through an intentional blank in this column.
                last = ""
                continue
            s = _cell_str(rows[r][c])
            if s:
                rows[r][c] = s
                if not _is_header_metadata_label(s):
                    last = s
            elif last:
                rows[r][c] = last
            else:
                rows[r][c] = ""
    filled: List[List[str]] = []
    for r, row in enumerate(rows):
        out: List[str] = []
        last = ""
        for c, v in enumerate(row):
            if explicit_empty[r][c]:
                out.append("")
                # Stop colspan propagation across an intentional blank column.
                last = ""
                continue
            s = _cell_str(v)
            if s:
                out.append(s)
                if not _is_header_metadata_label(s):
                    last = s
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
    """Ensure DataFrame column labels are unique (append ' (2)', ' (3)', …).

    Blank / missing headers stay blank. Extra blank columns are uniquified with
    zero-width spaces so pandas stays happy without inventing ``Col_N`` labels.
    """
    seen: Dict[str, int] = {}
    out: List[str] = []
    for raw in names:
        base = str(raw if raw is not None else "").strip("\u200b").strip()
        if base == "":
            n = seen.get("", 0)
            seen[""] = n + 1
            out.append("\u200b" * n if n else "")
            continue
        n = seen.get(base, 0) + 1
        seen[base] = n
        out.append(base if n == 1 else f"{base} ({n})")
    return out

def _is_placeholder_col_name(name: Any) -> bool:
    """True for blank headers and legacy ``Col_N`` stubs."""
    s = str(name or "").replace("\u200b", "").strip()
    if not s:
        return True
    return bool(re.match(r"^Col_\d+$", s, re.I))


def _set_col_header(
    names: List[str],
    meta: List[dict],
    index: int,
    label: str,
    *,
    header_path: Optional[List[str]] = None,
) -> None:
    path = [str(p) for p in (header_path or [label]) if str(p).strip()]
    if not path:
        path = [label]
    names[index] = path[-1]
    if index < len(meta):
        meta[index] = {
            **meta[index],
            "name": path[-1],
            "header_group": path[-2] if len(path) >= 2 else None,
            "header_path": path,
        }


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
    if first and not _is_placeholder_col_name(first):
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
    meta = [dict(m) for m in (column_meta or [])]
    while len(meta) < len(names):
        meta.append({"name": names[len(meta)], "header_group": None, "header_path": [names[len(meta)]]})
    _set_col_header(names, meta, 0, "S.No.")
    return names, meta


def _body_col_values(body_rows: Sequence[Sequence[Any]], col: int, *, limit: int = 24) -> List[str]:
    vals: List[str] = []
    for row in body_rows[:limit]:
        if col >= len(row):
            continue
        s = _cell_str(row[col])
        if s:
            vals.append(s)
    return vals


def _looks_like_serial_body(values: Sequence[str]) -> bool:
    if len(values) < 3:
        return False
    hits = sum(1 for v in values if re.match(r"^\d{1,4}$", v.strip()))
    return hits >= max(3, int(len(values) * 0.6))


def _looks_like_place_name_body(values: Sequence[str]) -> bool:
    if len(values) < 3:
        return False
    hits = 0
    for v in values:
        s = v.strip()
        if re.match(r"^\d+(\.\d+)?%?$", s.replace(",", "")):
            continue
        letters = re.findall(r"[A-Za-z]", s)
        if len(letters) >= 3 and len(s) >= 3:
            hits += 1
    return hits >= max(3, int(len(values) * 0.55))


def _looks_like_rural_urban_body(values: Sequence[str]) -> bool:
    """Require an explicit Rural/Urban token — bare Total rows are not enough."""
    tokens = {re.sub(r"\s+", " ", v).strip().lower() for v in values}
    rural_urban = {
        "rural",
        "urban",
        "i. rural",
        "ii. urban",
        "rural total",
        "urban total",
        "i rural",
        "ii urban",
    }
    return bool(tokens & rural_urban)


def _looks_like_age_band_body(values: Sequence[str]) -> bool:
    if len(values) < 3:
        return False
    pat = re.compile(
        r"^(?:below\s*\d+|\d+\s*[-–]\s*\d+|\d+\s*\+|\d+\s*and\s*above|above\s*\d+|not\s*stated|all\s*ages?|total)$",
        re.I,
    )
    hits = sum(1 for v in values if pat.match(re.sub(r"\s+", " ", v).strip()))
    return hits >= max(3, int(len(values) * 0.55))


def _looks_like_birth_order_leaf_name(name: str) -> bool:
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    s = re.sub(r"\s*\(\d+\)$", "", s).strip()
    return bool(
        re.match(
            r"^(?:\d+|>\s*\d+|≥\s*\d+|\d+\+|not\s*stated|ns|all)$",
            s,
            re.I,
        )
    )


def _recover_placeholder_column_headers(
    leaf_names: List[str],
    column_meta: List[dict],
    body_rows: Sequence[Sequence[Any]],
) -> Tuple[List[str], List[dict]]:
    """Replace ``Col_N`` stubs using body shape + Birth order grouping.

    Guard-only for empty ruled-box stubs (Age of mother, Rural/Urban, S.No./
    District). Does not rename already-meaningful headers.
    """
    if not leaf_names:
        return leaf_names, column_meta
    names = list(leaf_names)
    meta = [dict(m) for m in (column_meta or [])]
    while len(meta) < len(names):
        meta.append({
            "name": names[len(meta)],
            "header_group": None,
            "header_path": [names[len(meta)]],
        })

    col0_vals = _body_col_values(body_rows, 0)
    col1_vals = _body_col_values(body_rows, 1) if len(names) > 1 else []

    # S.No. + District / place when both leading headers are placeholders.
    if (
        len(names) >= 2
        and _is_placeholder_col_name(names[0])
        and _is_placeholder_col_name(names[1])
        and _looks_like_serial_body(col0_vals)
        and _looks_like_place_name_body(col1_vals)
    ):
        _set_col_header(names, meta, 0, "S.No.")
        _set_col_header(names, meta, 1, "District")

    # Single stub: Rural / Urban / Total rows.
    if _is_placeholder_col_name(names[0]) and _looks_like_rural_urban_body(col0_vals):
        _set_col_header(names, meta, 0, "Rural/ Urban")
        # Adjacent blank stub often holds Town / place names.
        if (
            len(names) >= 2
            and _is_placeholder_col_name(names[1])
            and _looks_like_place_name_body(col1_vals)
        ):
            _set_col_header(names, meta, 1, "Town")

    # Single stub: age-of-mother bands (Below 15, 15-19, …).
    if _is_placeholder_col_name(names[0]) and _looks_like_age_band_body(col0_vals):
        _set_col_header(names, meta, 0, "Age of mother")
    # Truncated wrap stub ("mother" / "Age of") with age-band body.
    elif (
        re.match(r"^(?:mother|age\s+of)$", str(names[0] or "").strip(), re.I)
        and _looks_like_age_band_body(col0_vals)
    ):
        _set_col_header(names, meta, 0, "Age of mother")

    # Structural: trailing grand-Total must not stay under a colspan parent.
    last_i = len(names) - 1
    if last_i >= 1:
        last_leaf = str(meta[last_i].get("name") or names[last_i])
        last_path = [str(p) for p in (meta[last_i].get("header_path") or []) if str(p).strip()]
        if re.match(r"^total(?:\s*\(\d+\))?$", last_leaf, re.I) and len(last_path) >= 2:
            _set_col_header(names, meta, last_i, last_leaf, header_path=[last_leaf])

    # Attach Birth order / Birth weight parents when stub is the row axis
    # (legacy blank-stub recovery path; repair already parks the group).
    stub0 = str(names[0] or "").strip().lower()
    birth_order_stub = (
        "age of mother" in stub0
        or stub0 in {"mother", "age of"}
        or "duration of marriage" in stub0
        or ("level of education" in stub0 and "mother" in stub0)
    )
    birth_weight_stub = "duration of pregnancy" in stub0 or "pregnancy" in stub0

    def _looks_like_weight_leaf_name(name: str) -> bool:
        s = re.sub(r"\s+", " ", str(name or "")).strip()
        s = re.sub(r"\s*\(\d+\)$", "", s).strip()
        return bool(
            re.match(
                r"^(?:<\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?|"
                r"\d+\+|not\s*stated|ns)$",
                s,
                re.I,
            )
        )

    order_leaf_idxs = [
        i for i, n in enumerate(names)
        if i > 0 and _looks_like_birth_order_leaf_name(str(n))
    ]
    if birth_order_stub and len(order_leaf_idxs) >= 3:
        for i in order_leaf_idxs:
            leaf = str(meta[i].get("name") or names[i])
            if i == last_i and re.match(r"^total(?:\s*\(\d+\))?$", leaf, re.I):
                continue
            path = [str(p) for p in (meta[i].get("header_path") or []) if str(p).strip()]
            if len(path) >= 2:
                continue
            _set_col_header(names, meta, i, leaf, header_path=["Birth order", leaf])
        last_leaf = str(meta[last_i].get("name") or names[last_i])
        last_path = [str(p) for p in (meta[last_i].get("header_path") or []) if str(p).strip()]
        if re.match(r"^total(?:\s*\(\d+\))?$", last_leaf, re.I) and len(last_path) >= 2:
            _set_col_header(names, meta, last_i, last_leaf, header_path=[last_leaf])

    weight_leaf_idxs = [
        i for i, n in enumerate(names)
        if i > 0 and _looks_like_weight_leaf_name(str(n))
    ]
    if birth_weight_stub and len(weight_leaf_idxs) >= 3:
        for i in weight_leaf_idxs:
            leaf = str(meta[i].get("name") or names[i])
            if i == last_i and re.match(r"^total(?:\s*\(\d+\))?$", leaf, re.I):
                continue
            path = [str(p) for p in (meta[i].get("header_path") or []) if str(p).strip()]
            if len(path) >= 2:
                continue
            _set_col_header(names, meta, i, leaf, header_path=["Birth weight (Kg)", leaf])
        last_leaf = str(meta[last_i].get("name") or names[last_i])
        last_path = [str(p) for p in (meta[last_i].get("header_path") or []) if str(p).strip()]
        if re.match(r"^total(?:\s*\(\d+\))?$", last_leaf, re.I) and len(last_path) >= 2:
            _set_col_header(names, meta, last_i, last_leaf, header_path=[last_leaf])

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
    "_recover_placeholder_column_headers",
    "detect_header_rows",
    "flatten_headers",
    "resolve_column_headers",
]
