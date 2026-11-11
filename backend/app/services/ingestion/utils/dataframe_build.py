"""Build DataFrames for Excel/CSV upload without PDF header absorption.

PDF ``dataframe_from_extracted_rows`` is aggressive about multi-level headers
(government PDF grids). Spreadsheet upload decides header depth with a
conservative rule:

- Default: one header row (protects text-heavy / code-like body rows).
- Multi-level only when the claimed header block shows merge/group evidence
  (consecutive repeated labels), using the catalogue heuristic as a candidate.
- Preview ``header_path`` still comes from PDF ``resolve_column_headers``, but
  only on the truncated header matrix — never by scanning body rows.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Set, Tuple

from app.services.ingestion.utils.grid import cell_str
from app.services.metadata.excel_facts import heuristic_structure, looks_like_data_row


def _blank_row(row: Sequence[Any]) -> bool:
    return all(not cell_str(c) for c in row)


def _has_consecutive_repeats(row: Sequence[Any]) -> bool:
    """True when adjacent cells share a label (Excel colspan / merge-fill)."""
    vals = [cell_str(c) for c in row]
    for left, right in zip(vals, vals[1:]):
        if left and right and left.upper() == right.upper():
            return True
    return False


def _clamp_header_rows(
    body: List[List[Any]], header_rows: int, skip_set: Set[int]
) -> Tuple[int, Set[int]]:
    """If a claimed header row after the first looks like data, keep one header."""
    if header_rows <= 1 or not body:
        return max(header_rows, 1), skip_set
    claimed = body[1:header_rows]
    if any((not _blank_row(r)) and looks_like_data_row(r) for r in claimed):
        return 1, {i for i in skip_set if i < 1}
    return header_rows, skip_set


def _spreadsheet_header_plan(
    padded: List[List[Any]], n_cols: int
) -> Tuple[int, Set[int]]:
    """Conservative header_rows for Excel/CSV (catalogue heuristic + merge gate)."""
    structure = heuristic_structure(padded, n_cols)
    header_rows = int(structure.get("header_rows") or 1)
    skip_set: Set[int] = set(structure.get("skip_rows") or [])
    header_rows, skip_set = _clamp_header_rows(padded, header_rows, skip_set)

    non_blank = [i for i, r in enumerate(padded) if not _blank_row(r)]
    # Never absorb every filled row into headers — leave at least one body row.
    if header_rows >= len(non_blank) and len(non_blank) >= 2:
        header_rows = 1
        skip_set = {i for i in skip_set if i < 1}

    if header_rows <= 1:
        return 1, skip_set

    matrix = [
        padded[i]
        for i in range(header_rows)
        if i not in skip_set and not _blank_row(padded[i])
    ]
    # Multi-level only with colspan/merge-fill evidence; otherwise body text
    # rows that look like short labels would be swallowed as header bands.
    if not any(_has_consecutive_repeats(r) for r in matrix):
        return 1, {i for i in skip_set if i < 1}

    return header_rows, skip_set


def dataframe_from_spreadsheet_rows(rows: Optional[List[List[Any]]]):
    """
    Build a pandas DataFrame from an Excel/CSV grid.

    Conservative header detection for spreadsheets; PDF-only path unchanged.
    """
    import pandas as pd
    from app.services.extraction.pdf.utils.header_utils import (
        _fill_blank_leading_serial_header,
        _uniquify_columns,
        resolve_column_headers,
    )

    if not rows:
        return pd.DataFrame()

    n_cols = max((len(r) for r in rows), default=0)
    if n_cols == 0:
        return pd.DataFrame()

    padded: List[List[Any]] = [
        list(r) + [None] * (n_cols - len(r)) for r in rows
    ]
    header_rows, skip_set = _spreadsheet_header_plan(padded, n_cols)
    header_rows = max(1, min(header_rows, len(padded)))

    header_matrix = [
        padded[i]
        for i in range(header_rows)
        if i not in skip_set and not _blank_row(padded[i])
    ]
    if not header_matrix:
        header_matrix = [padded[0]]
        header_rows = 1
        skip_set = set()

    resolved = resolve_column_headers(header_matrix, n_cols)
    leaf_names = _uniquify_columns([c["name"] for c in resolved])
    column_meta = []
    for i in range(n_cols):
        path = [str(p) for p in (resolved[i].get("header_path") or []) if str(p).strip()]
        if not path:
            path = [resolved[i].get("name") or leaf_names[i]]
        display_leaf = str(path[-1] if path else (resolved[i].get("name") or leaf_names[i]))
        column_meta.append({
            "name": display_leaf,
            "header_group": path[-2] if len(path) >= 2 else None,
            "header_path": path,
        })
    leaf_names, column_meta = _fill_blank_leading_serial_header(leaf_names, column_meta)

    body: List[List[Any]] = []
    for i in range(header_rows, len(padded)):
        if i in skip_set or _blank_row(padded[i]):
            continue
        body.append([cell_str(v) or None for v in padded[i]])

    # Column-number strips skipped for naming stay visible as leading body rows.
    leading_index: List[List[Any]] = []
    for i in range(header_rows, len(padded)):
        if i not in skip_set:
            break
        if _blank_row(padded[i]):
            continue
        leading_index.append([cell_str(v) or None for v in padded[i]])
    if leading_index:
        body = leading_index + body

    if not body:
        df = pd.DataFrame(columns=leaf_names)
    else:
        df = pd.DataFrame(body, columns=leaf_names)
    df.attrs["dhara_column_meta"] = column_meta
    return df


__all__ = [
    "dataframe_from_spreadsheet_rows",
]
