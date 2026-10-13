"""Extraction / validation service — shared PDF, Excel, CSV upload validator."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from app.services.extraction.pdf.confidence_validation.orchestrate import (
    run_pipeline,
    run_post_extraction_validation,
)

__all__ = ["run_pipeline", "run_post_extraction_validation", "validate"]


def validate(
    pre_input: Dict[str, Any],
    *,
    api_key: Optional[str] = None,
    on_progress: Optional[Callable[[str, int, str], None]] = None,
    **kwargs: Any,
) -> Dict[int, Dict]:
    """Run shared post-extraction confidence / LLM validation."""
    return run_post_extraction_validation(
        pre_input, api_key=api_key, on_progress=on_progress, **kwargs
    )
