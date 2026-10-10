"""Orchestrate confidence split + LLM / heuristic validation."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import openai
import pandas as pd
import pymupdf

from app.services.extraction.pdf.confidence_validation.confidence_split import (
    _llm_pages_missing_tables,
    split_by_confidence,
)
from app.services.extraction.pdf.confidence_validation.heuristic import heuristic_accept_pages
from app.services.extraction.pdf.confidence_validation.llm import validate_all_pages_batched
from app.services.extraction.pdf.utils.pymupdf import log, run_pdf_extraction

def run_post_extraction_validation(
    pages_grouped: Dict[int, List[Dict[str, Any]]],
    page_text: Dict[int, str],
    *,
    pdf_path: Optional[Path] = None,
    outline_index: Optional[Dict[int, List[str]]] = None,
    api_key: Optional[str] = None,
    on_progress: Optional[Callable[[str, int, str], None]] = None,
) -> Dict[int, Dict[str, Any]]:
    """Shared confidence split + LLM validation (PDF, Excel, CSV after ingest)."""

    def progress(stage: str, percent: int, message: str) -> None:
        log(message)
        if on_progress:
            on_progress(stage, percent, message)

    outline_index = outline_index or {}
    high_results, llm_pages, reason_counts = split_by_confidence(
        pages_grouped,
        page_text,
        pdf_path=pdf_path,
        outline_index=outline_index,
    )
    progress(
        "classify_confidence",
        55,
        f"{len(high_results)} unit(s) auto-accepted, {len(llm_pages)} unit(s) need AI validation",
    )

    validated_by_page: Dict[int, Dict[str, Any]] = dict(high_results)
    if llm_pages:
        key = (api_key or "").strip() or None
        if key:
            llm_results = validate_all_pages_batched(
                llm_pages,
                page_text,
                api_key=key,
                progress_cb=lambda done, total: progress(
                    "validate",
                    55 + int(45 * done / total),
                    f"Validated {done}/{total} unit(s)",
                ),
            )
            validated_by_page.update(llm_results)
            missing = _llm_pages_missing_tables(llm_pages, llm_results)
            if missing:
                progress(
                    "validate",
                    90,
                    f"LLM returned no tables for {len(missing)} unit(s) — "
                    f"keeping grid extractions for review",
                )
                heuristic = heuristic_accept_pages(
                    missing,
                    page_text,
                    pdf_path=pdf_path,
                    outline_index=outline_index,
                    review_reason="llm_validation_failed_heuristic",
                )
                validated_by_page.update(heuristic)
        else:
            progress(
                "validate",
                60,
                f"No MEITY-empanelled LLM key — heuristic-accepting {len(llm_pages)} unit(s) for review",
            )
            heuristic = heuristic_accept_pages(
                llm_pages,
                page_text,
                pdf_path=pdf_path,
                outline_index=outline_index,
            )
            validated_by_page.update(heuristic)
            progress("validate", 95, f"Heuristic-accepted {len(heuristic)} unit(s)")

    progress("done", 100, f"Pipeline complete -- {len(validated_by_page)} unit(s) with tables")
    return dict(sorted(validated_by_page.items()))




def run_pipeline(pdf_path: Path, on_progress: Optional[Callable[[str, int, str], None]] = None,
                  api_key: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    """Programmatic entry point for running the full pipeline on an arbitrary
    PDF (used by the /api/pdf/* endpoints in main.py for a user-uploaded
    file). Mirrors main()'s CLI orchestration but takes an explicit path,
    returns the validated-by-page dict directly instead of writing a JSON
    file, and reports coarse progress via on_progress(stage, percent, message)
    so a caller (e.g. a FastAPI background job) can surface a progress bar.

    Runs synchronously and blocks for as long as the pipeline takes (minutes,
    for a large PDF) -- callers on an event loop must wrap this in
    asyncio.to_thread rather than awaiting it directly."""
    pages_grouped, page_text, outline_index = run_pdf_extraction(pdf_path, on_progress=on_progress)
    return run_post_extraction_validation(
        pages_grouped,
        page_text,
        pdf_path=pdf_path,
        outline_index=outline_index,
        api_key=api_key,
        on_progress=on_progress,
    )
