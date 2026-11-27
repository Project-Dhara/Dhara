"""Additive splitter for glued multi-block ruled grids (same column schema).

Marriage-registration style pages repeat::

    header → data → Total → From…TO… → district → header → …

PyMuPDF returns one bbox; the existing TABLE-marker split does not fire.
This module only runs when the pattern is clear; otherwise it is a no-op.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

_Seg = Tuple[List[List[Any]], int, int]

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
_DATE_RANGE_RE = re.compile(
    r"from\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s+to\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}",
    re.I,
)
_TOTAL_RE = re.compile(r"^total\s*$", re.I)
# Header-ish labels common on these stacks (and generic S.No. grids).
_HEADER_HINTS = frozenset(
    {
        "sno",
        "s",
        "no",
        "sl",
        "slno",
        "marriage",
        "act",
        "total",
        "application",
        "applications",
        "received",
        "registration",
        "registered",
        "issued",
        "done",
        "name",
        "district",
    }
)


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).replace("\n", " ").strip()


def _row_text(row: Sequence[Any]) -> str:
    return " ".join(_cell_str(c) for c in row if _cell_str(c)).strip()


def _blank(row: Sequence[Any]) -> bool:
    return not any(_cell_str(c) for c in row)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _pad_row(row: Sequence[Any], n_cols: int) -> List[Any]:
    cells = list(row)
    if len(cells) < n_cols:
        cells.extend([None] * (n_cols - len(cells)))
    return cells[:n_cols]


def _nonempty_cells(row: Sequence[Any]) -> List[str]:
    return [_cell_str(c) for c in row if _cell_str(c)]


def _row_token_set(row: Sequence[Any]) -> set[str]:
    return _tokens(_row_text(row))


def _overlap_ratio(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / float(max(len(a), len(b)))


def _looks_like_header_row(row: Sequence[Any], *, min_cells: int = 3) -> bool:
    cells = _nonempty_cells(row)
    if len(cells) < min_cells:
        return False
    # Mostly non-numeric labels.
    numeric = 0
    for c in cells:
        compact = c.replace(",", "").replace(".", "").replace("%", "").strip()
        if compact.isdigit():
            numeric += 1
    if numeric >= max(2, len(cells) // 2):
        return False
    toks = _tokens(" ".join(cells))
    if len(toks) < 3:
        return False
    return bool(toks & _HEADER_HINTS) or len(cells) >= 3


def _is_total_row(row: Sequence[Any]) -> bool:
    cells = _nonempty_cells(row)
    if not cells:
        return False
    # Standalone "Total" in an early cell (merged label columns), not a
    # header like "Total No. of application Received".
    for c in cells[:2]:
        if _TOTAL_RE.match(c.replace(".", "").strip()):
            return True
    return False


def _is_date_range_row(row: Sequence[Any]) -> bool:
    return bool(_DATE_RANGE_RE.search(_row_text(row)))


def is_date_range_row(row: Sequence[Any]) -> bool:
    """Public alias for Preview banner re-inject (marriage registration)."""
    return _is_date_range_row(row)


def _is_short_label_row(row: Sequence[Any], n_cols: int) -> bool:
    """District / place banner: one (or few) text cells, short, not a header."""
    cells = _nonempty_cells(row)
    if not cells or len(cells) > 2:
        return False
    text = " ".join(cells).strip()
    if not text or len(text) > 48:
        return False
    if _is_date_range_row(row) or _is_total_row(row):
        return False
    if _looks_like_header_row(row, min_cells=3):
        return False
    # Avoid treating a lone serial or measure as a label.
    compact = text.replace(",", "").replace(".", "").strip()
    if compact.isdigit():
        return False
    return True


def is_short_label_row(row: Sequence[Any], n_cols: int) -> bool:
    """Public alias for Preview banner re-inject (marriage registration)."""
    return _is_short_label_row(row, n_cols)


_MARRIAGE_HEADER_TOKENS = frozenset(
    {
        "marriage",
        "act",
        "application",
        "applications",
        "received",
        "registration",
        "registered",
        "issued",
        "done",
    }
)


def looks_like_marriage_act_header_row(row: Sequence[Any]) -> bool:
    """True for Act-wise marriage registration column-header rows."""
    if not _looks_like_header_row(row, min_cells=3):
        return False
    toks = _row_token_set(row)
    # Require "marriage" + at least one schema cue (act / application / …).
    if "marriage" not in toks:
        return False
    return bool(toks & (_MARRIAGE_HEADER_TOKENS - {"marriage"}))


def _find_header_prototype(rows: List[List[Any]]) -> Tuple[Optional[int], set[str]]:
    for i, row in enumerate(rows):
        if _blank(row):
            continue
        if _looks_like_header_row(row):
            return i, _row_token_set(row)
    return None, set()


def _find_header_repeats(
    rows: List[List[Any]], proto: set[str], *, first_idx: int
) -> List[int]:
    hits = [first_idx]
    for i in range(first_idx + 1, len(rows)):
        row = rows[i]
        if _blank(row):
            continue
        if not _looks_like_header_row(row):
            continue
        if _overlap_ratio(proto, _row_token_set(row)) >= 0.55:
            hits.append(i)
    return hits


def _has_separator_between(rows: List[List[Any]], a: int, b: int, n_cols: int) -> bool:
    for i in range(a + 1, b):
        row = rows[i]
        if _blank(row):
            continue
        if _is_total_row(row) or _is_date_range_row(row) or _is_short_label_row(row, n_cols):
            return True
    return False


def looks_like_stacked_schema_blocks(rows: Optional[Sequence[Sequence[Any]]]) -> bool:
    """True only when ≥2 same-schema headers appear with a Total/date/label between."""
    if not rows or len(rows) < 8:
        return False
    n_cols = max((len(r) for r in rows), default=0)
    if n_cols < 3:
        return False
    padded = [_pad_row(r, n_cols) for r in rows]
    h0, proto = _find_header_prototype(padded)
    if h0 is None or len(proto) < 3:
        return False
    repeats = _find_header_repeats(padded, proto, first_idx=h0)
    if len(repeats) < 2:
        return False
    # Require a separator cue between the first two header blocks.
    if not _has_separator_between(padded, repeats[0], repeats[1], n_cols):
        return False
    return True


def _banner_start_before(rows: List[List[Any]], header_idx: int, n_cols: int) -> int:
    """Walk back over date/district/blank rows; stop at Total or data."""
    start = header_idx
    i = header_idx - 1
    while i >= 0:
        row = rows[i]
        if _blank(row):
            start = i
            i -= 1
            continue
        if _is_date_range_row(row) or _is_short_label_row(row, n_cols):
            start = i
            i -= 1
            continue
        break
    return start


def split_stacked_schema_blocks(
    rows: Optional[Sequence[Sequence[Any]]],
) -> List[_Seg]:
    """
    Split a glued same-schema stack into one segment per block.

    Returns ``[(seg_rows, start_idx, end_idx), ...]`` with indices into the
    padded input (end exclusive), matching ``split_extracted_rows_on_table_markers``.
    """
    if not rows:
        return []
    n_cols = max((len(r) for r in rows), default=0)
    if n_cols == 0:
        return []
    padded = [_pad_row(r, n_cols) for r in rows]

    if not looks_like_stacked_schema_blocks(padded):
        return [(padded, 0, len(padded))]

    h0, proto = _find_header_prototype(padded)
    assert h0 is not None
    repeats = _find_header_repeats(padded, proto, first_idx=h0)
    if len(repeats) < 2:
        return [(padded, 0, len(padded))]

    # Segment starts: first block at 0 (or first content); later blocks at
    # banner run immediately before each repeated header.
    starts: List[int] = [0]
    for hi in repeats[1:]:
        starts.append(_banner_start_before(padded, hi, n_cols))

    segments: List[_Seg] = []
    for j, start in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(padded)
        chunk = [list(r) for r in padded[start:end]]
        while chunk and _blank(chunk[-1]):
            chunk.pop()
        while chunk and _blank(chunk[0]):
            chunk.pop(0)
            start += 1
        if len(chunk) >= 2:
            segments.append((chunk, start, end))

    return segments or [(padded, 0, len(padded))]
