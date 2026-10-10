"""Shared types for the data ingestion layer (format-independent contracts)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from typing_extensions import NotRequired, TypedDict

SourceType = Literal["pdf", "excel", "csv"]

# One logical table region (PDF page, Excel sheet+block, or CSV file).
UnitId = int

CandidateDict = Dict[str, Any]
PagesGrouped = Dict[UnitId, List[CandidateDict]]
UnitContextText = Dict[UnitId, str]


class PreValidationInput(TypedDict):
    """
    Grid candidates + per-unit grounding text, before confidence / LLM validation.

    Produced by ingestion adapters (Excel, CSV, PDF extract). Consumed by
    extraction validation (``app.services.extraction``).
    """

    pages_grouped: PagesGrouped
    unit_context: UnitContextText
    source_type: NotRequired[SourceType]
    source_file: NotRequired[str]
    # PDF-only: absolute path for title/bbox helpers during validation.
    source_path: NotRequired[str]
    outline_index: NotRequired[Dict[int, List[str]]]
