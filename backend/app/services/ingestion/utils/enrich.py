"""Attach source metadata to extraction output tables."""

from __future__ import annotations

from typing import Dict

from app.services.ingestion.contracts import SourceType


def tag_tables_with_source_type(result: Dict[int, Dict], source_type: SourceType) -> Dict[int, Dict]:
    for _unit, page in result.items():
        for table in page.get("tables") or []:
            table["source_type"] = source_type
    return result
