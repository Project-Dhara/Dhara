"""Compatibility re-export — contracts live in ``app.services.ingestion.contracts``."""
from app.services.ingestion.contracts import (  # noqa: F401
    CandidateDict,
    PagesGrouped,
    PreValidationInput,
    SourceType,
    UnitContextText,
    UnitId,
)

__all__ = [
    "CandidateDict",
    "PagesGrouped",
    "PreValidationInput",
    "SourceType",
    "UnitContextText",
    "UnitId",
]
