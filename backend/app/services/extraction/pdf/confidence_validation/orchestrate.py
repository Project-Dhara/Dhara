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

from app.services.llm_prompts import DEFER_TITLE_FILL
from app.services.extraction.pdf.confidence_validation.confidence_split import (
    _llm_pages_missing_tables,
    split_by_confidence,
)
from app.services.extraction.pdf.confidence_validation.heuristic import heuristic_accept_pages
from app.services.extraction.pdf.confidence_validation.llm import validate_all_pages_batched
from app.services.extraction.pdf.confidence_validation.title_fill import (
    ensure_usable_titles_on_pages,
)
from app.services.extraction.pdf.utils.pymupdf import log, run_pdf_extraction


def _partition_llm_pages_by_tier(
    llm_pages: Dict[int, List[Dict[str, Any]]],
    llm_tiers: Dict[int, str],
) -> Tuple[Dict[int, List[Dict[str, Any]]], Dict[int, List[Dict[str, Any]]]]:
    header_pages: Dict[int, List[Dict[str, Any]]] = {}
    full_pages: Dict[int, List[Dict[str, Any]]] = {}
    for page_num, cands in (llm_pages or {}).items():
        if (llm_tiers or {}).get(page_num) == "header":
            header_pages[page_num] = cands
        else:
            full_pages[page_num] = cands
    return header_pages, full_pages


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
    n_units = len(pages_grouped)
    progress(
        "classify_confidence",
        46,
        f"Scoring confidence for {n_units} unit(s)",
    )
    high_results, llm_pages, reason_counts, llm_tiers = split_by_confidence(
        pages_grouped,
        page_text,
        pdf_path=pdf_path,
        outline_index=outline_index,
        progress_cb=lambda done, total: progress(
            "classify_confidence",
            46 + int(9 * done / max(total, 1)),
            f"Scored {done}/{total} unit(s)",
        ),
    )
    header_pages, full_pages = _partition_llm_pages_by_tier(llm_pages, llm_tiers)
    progress(
        "classify_confidence",
        55,
        f"{len(high_results)} unit(s) auto-accepted, {len(llm_pages)} unit(s) need AI "
        f"({len(header_pages)} header-fix, {len(full_pages)} full reconstruct)",
    )
    if reason_counts:
        top = sorted(reason_counts.items(), key=lambda kv: -kv[1])[:5]
        for reason, count in top:
            log(f"  [llm bucket] {count}x: {reason}")

    validated_by_page: Dict[int, Dict[str, Any]] = dict(high_results)
    if llm_pages:
        key = (api_key or "").strip() or None
        if key:
            llm_results: Dict[int, Dict[str, Any]] = {}
            total_llm = len(llm_pages)
            done_llm = 0

            def _progress_from(offset_done: int):
                def _cb(done: int, total: int) -> None:
                    nonlocal done_llm
                    # ``done`` is within the current tier; combine with prior tiers.
                    combined = offset_done + done
                    done_llm = combined
                    progress(
                        "validate",
                        55 + int(40 * combined / max(total_llm, 1)),
                        f"Validated {combined}/{total_llm} unit(s)",
                    )
                return _cb

            if header_pages:
                progress(
                    "validate",
                    56,
                    f"AI header-fix on {len(header_pages)} unit(s) (body from ruled grids)",
                )
                llm_results.update(
                    validate_all_pages_batched(
                        header_pages,
                        page_text,
                        api_key=key,
                        mode="header",
                        progress_cb=_progress_from(0),
                    )
                )
            if full_pages:
                progress(
                    "validate",
                    56 + int(40 * len(header_pages) / max(total_llm, 1)),
                    f"AI full reconstruct on {len(full_pages)} unit(s)",
                )
                llm_results.update(
                    validate_all_pages_batched(
                        full_pages,
                        page_text,
                        api_key=key,
                        mode="full",
                        progress_cb=_progress_from(len(header_pages)),
                    )
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

    # Title pass: clear gibberish; AI-fill crisp titles when missing (unless deferred).
    # PDF_DEFER_TITLE_FILL=1 skips the LLM calls for speed.
    progress(
        "validate",
        96,
        "Checking table titles"
        if DEFER_TITLE_FILL
        else "Filling missing titles with AI",
    )
    ensure_usable_titles_on_pages(
        validated_by_page,
        api_key=None if DEFER_TITLE_FILL else api_key,
    )
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
