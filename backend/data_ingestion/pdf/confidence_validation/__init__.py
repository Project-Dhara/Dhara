"""Compatibility shim — public API re-exported from app.services.extraction.pdf."""
from app.services.extraction.pdf.confidence_validation import *  # noqa: F403
from app.services.extraction.pdf.confidence_validation import (
    build_batch_validation_prompt,
    build_validation_prompt,
    heuristic_accept_pages,
    run_pipeline,
    run_post_extraction_validation,
    split_by_confidence,
    validate_all_pages,
    validate_all_pages_batched,
    validate_batch,
    validate_page,
)

__all__ = [
    "build_batch_validation_prompt",
    "build_validation_prompt",
    "heuristic_accept_pages",
    "run_pipeline",
    "run_post_extraction_validation",
    "split_by_confidence",
    "validate_all_pages",
    "validate_all_pages_batched",
    "validate_batch",
    "validate_page",
]
