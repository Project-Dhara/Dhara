"""Shared types for the data ingestion layer."""

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
    Grid candidates + per-unit grounding text for extraction validation
    (confidence split + LLM). Excel/CSV produce this after data ingestion;
    PDF will use the same shape later.
    """

    pages_grouped: PagesGrouped
    unit_context: UnitContextText
    source_type: NotRequired[SourceType]
    source_file: NotRequired[str]
