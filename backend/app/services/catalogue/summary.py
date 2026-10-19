"""Crisp catalogue AI summaries from group metadata + table titles.

Keeps the Summary tab narrative short and factual — rejects OCR dumps,
row dumps, and other gibberish that sometimes lands in ``description``.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_EMPTY = frozenset({"-", "—", "–", "n/a", "na", "none", "null", ""})
_MAX_SUMMARY_CHARS = 360


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def is_usable_catalogue_description(text: Any) -> bool:
    """False when the text is empty, a placeholder, or looks like dumped noise."""
    s = _clean(text)
    if not s or s.lower() in _EMPTY:
        return False
    if len(s) > 600:
        return False
    if s.count("\n") >= 4:
        return False
    # JSON / markdown table / pipe grids
    if "{" in s or "[" in s:
        return False
    if s.count("|") >= 2:
        return False
    # Dense key:value sample dumps
    if s.count(":") >= 5 and (s.count(";") >= 2 or s.count(",") >= 8):
        return False
    alnum = sum(ch.isalnum() for ch in s)
    digits = sum(ch.isdigit() for ch in s)
    if alnum and (digits / alnum) > 0.45:
        return False
    # Bullet lists belong in key_statistics, not the AI summary
    if s.lstrip().startswith(("•", "-", "*")) and s.count("\n") >= 1:
        return False
    return True


def crisp_catalogue_description(text: str, *, max_len: int = _MAX_SUMMARY_CHARS) -> str:
    """Collapse whitespace and trim to a short sentence-bounded blurb."""
    s = _clean(text)
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx >= 72:
            return cut[: idx + 1].strip()
    trimmed = cut.rsplit(" ", 1)[0].rstrip(",;: ")
    return (trimmed + ".") if trimmed else s[:max_len]


def _table_titles_from_group_tables(tables: Optional[list]) -> list[str]:
    titles: list[str] = []
    for t in tables or []:
        if not isinstance(t, dict):
            continue
        name = _clean(t.get("title") or t.get("table_name") or t.get("name"))
        if name and name.lower() not in _EMPTY and name not in titles:
            titles.append(name)
        if len(titles) >= 6:
            break
    return titles


def synthesize_catalogue_summary(
    *,
    title: str = "",
    product: str = "",
    category: str = "",
    geography: str = "",
    frequency: str = "",
    time_period: str = "",
    table_titles: Optional[list[str]] = None,
    table_count: int = 0,
) -> str:
    """Build a short factual blurb from structured fields + table titles."""
    subject = _clean(title) or _clean(product) or "This release"
    about: list[str] = []
    cat = _clean(category)
    prod = _clean(product)
    if cat and cat.lower() not in _EMPTY:
        about.append(cat)
    if prod and prod.lower() not in _EMPTY and prod.lower() != subject.lower():
        about.append(prod)

    if about:
        lead = f"{subject} covers {', '.join(about[:2])}"
    else:
        lead = f"{subject} presents tabulated statistics"

    coverage: list[str] = []
    for part in (geography, time_period, frequency):
        p = _clean(part)
        if p and p.lower() not in _EMPTY and p not in ("—", "–"):
            coverage.append(p)
    if coverage:
        lead = f"{lead} for {', '.join(coverage)}."
    else:
        lead = f"{lead}."

    titles = [t for t in (table_titles or []) if _clean(t)]
    n = table_count or len(titles)
    if titles:
        if len(titles) == 1:
            return crisp_catalogue_description(
                f"{lead} It includes the table “{titles[0]}”."
            )
        shown = ", ".join(f"“{t}”" for t in titles[:3])
        extra = f" (+{len(titles) - 3} more)" if len(titles) > 3 else ""
        if n > len(titles):
            extra = f" ({n} tables)" if not extra else extra
        return crisp_catalogue_description(f"{lead} Tables include {shown}{extra}.")
    if n > 1:
        return crisp_catalogue_description(f"{lead} The release contains {n} tables.")
    return crisp_catalogue_description(lead)


def catalogue_display_summary(row: dict, tables: Optional[list] = None) -> str:
    """Summary shown on the catalogue Summary tab for one published group."""
    tables = tables if isinstance(tables, list) else []
    desc = row.get("description")
    if is_usable_catalogue_description(desc):
        return crisp_catalogue_description(str(desc))
    titles = _table_titles_from_group_tables(tables)
    return synthesize_catalogue_summary(
        title=str(row.get("title") or row.get("metadata_id") or ""),
        product=str(row.get("catalogue_product") or row.get("product") or ""),
        category=str(row.get("category") or ""),
        geography=str(row.get("geography") or ""),
        frequency=str(row.get("frequency") or ""),
        time_period=str(row.get("time_period") or ""),
        table_titles=titles,
        table_count=len(tables),
    )


__all__ = [
    "catalogue_display_summary",
    "crisp_catalogue_description",
    "is_usable_catalogue_description",
    "synthesize_catalogue_summary",
]
