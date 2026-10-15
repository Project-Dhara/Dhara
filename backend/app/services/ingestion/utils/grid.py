"""Grid / cell helpers for spreadsheet ingestion."""

from __future__ import annotations

import math
from typing import Any, List


def cell_str(v: Any) -> str:
    if v is None:
        return ""
    # Excel/openpyxl yields floats for numeric cells; keep whole numbers as ints.
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        if math.isfinite(v) and v.is_integer():
            return str(int(v))
        return str(v)
    if isinstance(v, int):
        return str(v)
    return str(v).strip()


def block_to_rows(block: List[List[Any]]) -> List[List[Any]]:
    out: List[List[Any]] = []
    for row in block:
        out.append([c if c is None or cell_str(c) else cell_str(c) or None for c in row])
    return out


def strip_uniform_banner_rows(rows: List[List[Any]]) -> List[List[Any]]:
    """Drop leading caption/id rows where every non-empty cell is identical.

    Spreadsheet blocks often start with a table-id or title repeated across
    columns. The shared PDF header flattener treats those as header levels and
    can consume the real column row + data; strip them first for Excel/CSV.
    """
    out = list(rows)
    while out:
        vals = [cell_str(c) for c in out[0] if cell_str(c)]
        if len(vals) >= 2 and len(set(vals)) == 1:
            out = out[1:]
            continue
        break
    return out


def context_text_from_grid(
    rows: List[List[Any]],
    *,
    sheet_name: str = "",
    filename: str = "",
    max_rows: int = 12,
) -> str:
    """Plain-text context for LLM grounding (caption rows, sheet name, etc.).

    Grid lines come first so title heuristics prefer real captions over the
    ``Source file:`` / ``Sheet:`` metadata trailer. Repeated merge-fill cells
    on a banner row are de-duplicated.
    """
    lines: List[str] = []
    for row in rows[:max_rows]:
        seen: set = set()
        parts: List[str] = []
        for c in row:
            s = cell_str(c)
            if s and s not in seen:
                seen.add(s)
                parts.append(s)
        if parts:
            lines.append(" ".join(parts))
    if filename:
        lines.append(f"Source file: {filename}")
    if sheet_name:
        lines.append(f"Sheet: {sheet_name}")
    return "\n".join(lines)[:3000]
