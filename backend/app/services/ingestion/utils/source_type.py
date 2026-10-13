"""Resolve upload source type from filename and optional client hint."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from app.services.ingestion.contracts import SourceType

_EXT_TO_SOURCE: Dict[str, SourceType] = {
    ".pdf": "pdf",
    ".xlsx": "excel",
    ".xls": "excel",
    ".csv": "csv",
}

_TYPE_HINT_ALIASES: Dict[str, SourceType] = {
    "pdf": "pdf",
    "excel": "excel",
    "xlsx": "excel",
    "xls": "excel",
    "csv": "csv",
}


def resolve_source_type(filename: str, type_hint: Optional[str] = None) -> SourceType:
    """Infer source type from extension; optional hint must agree."""
    name = (filename or "").lower().strip()
    ext = Path(name).suffix
    inferred = _EXT_TO_SOURCE.get(ext)
    if not inferred:
        raise ValueError(f"Unsupported file extension: {ext or '(none)'}")

    hint = (type_hint or "").strip().lower()
    if not hint:
        return inferred

    normalized = _TYPE_HINT_ALIASES.get(hint)
    if not normalized:
        raise ValueError(f"Unsupported type hint: {type_hint!r} (use pdf, excel, or csv)")
    if normalized != inferred:
        raise ValueError(
            f"type={type_hint!r} does not match file extension {ext!r} (expected {inferred})"
        )
    return normalized
