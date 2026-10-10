"""Grid / cell helpers for spreadsheet ingestion."""

from __future__ import annotations

from typing import Any, List


def cell_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def block_to_rows(block: List[List[Any]]) -> List[List[Any]]:
    out: List[List[Any]] = []
    for row in block:
        out.append([c if c is None or cell_str(c) else cell_str(c) or None for c in row])
    return out


def context_text_from_grid(
    rows: List[List[Any]],
    *,
    sheet_name: str = "",
    filename: str = "",
    max_rows: int = 12,
) -> str:
    """Plain-text context for LLM grounding (caption rows, sheet name, etc.)."""
    lines: List[str] = []
    if filename:
        lines.append(f"Source file: {filename}")
    if sheet_name:
        lines.append(f"Sheet: {sheet_name}")
    for row in rows[:max_rows]:
        parts = [cell_str(c) for c in row if cell_str(c)]
        if parts:
            lines.append(" ".join(parts))
    return "\n".join(lines)[:3000]
