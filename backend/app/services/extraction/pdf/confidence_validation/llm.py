"""LLM table reconstruction + semantic classification API calls."""
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

from app.services.llm_prompts import (
    BATCH_SIZE,
    BATCH_VALIDATION_MAX_TOKENS_CAP,
    LLM_VALIDATION_TEMPERATURE,
    MAX_TOKENS_PER_PAGE,
    OPENAI_MODEL,
    OPENAI_WORKERS,
    PDF_VALIDATION_RAW_TEXT_CHARS,
    RAW_TEXT_CHARS_PER_PAGE_BATCHED,
    SINGLE_PAGE_MAX_TOKENS,
    pdf_batch_validation_user_prompt,
    pdf_single_page_validation_user_prompt,
)
from app.services.extraction.pdf.confidence_validation.confidence_split import df_to_text
from app.services.extraction.pdf.confidence_validation.stamp import _stamp_llm_metadata
from app.services.extraction.pdf.utils.pymupdf import (
    _distinct_ruled_candidates,
    dedupe_candidates_by_bbox,
    log,
)

def build_validation_prompt(page_num: int, candidates: List[Dict[str, Any]], text: str) -> str:
    candidates = dedupe_candidates_by_bbox(candidates)
    ruled_n = len(_distinct_ruled_candidates(candidates))
    sections = [f"--- {t['method']}, table {i + 1} ---\n{df_to_text(t['df'])}" for i, t in enumerate(candidates)]
    count_hint = (
        f"Ruled-border detectors found {ruled_n} distinct table region(s) on this page. "
        f"Return exactly {ruled_n} object(s) in \"tables\" unless the raw text clearly shows otherwise.\n\n"
        if ruled_n else ""
    )

    return pdf_single_page_validation_user_prompt(
        page_num=page_num,
        raw_page_text=text[:PDF_VALIDATION_RAW_TEXT_CHARS],
        candidates_block=chr(10).join(sections)
        if sections
        else "(no table candidates extracted on this page)",
        count_hint=count_hint,
    )


def validate_page(client: openai.OpenAI, page_num: int, candidates: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    prompt = build_validation_prompt(page_num, candidates, text)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=SINGLE_PAGE_MAX_TOKENS,
        temperature=LLM_VALIDATION_TEMPERATURE,
    )
    text_out = resp.choices[0].message.content
    try:
        return json.loads(text_out)
    except json.JSONDecodeError:
        cleaned = re.sub(r"```[a-z]*\n?", "", text_out).strip().rstrip("`")
        return json.loads(cleaned)


def validate_all_pages(pages_grouped: Dict[int, List[Dict[str, Any]]], page_text: Dict[int, str],
                        n_workers: int = OPENAI_WORKERS,
                        api_key: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    key = (api_key or "").strip()
    if not key:
        return {}
    client = openai.OpenAI(api_key=key)
    validated: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(validate_page, client, page_num, candidates, page_text.get(page_num, "")): page_num
            for page_num, candidates in pages_grouped.items()
        }
        done = 0
        for future in as_completed(futures):
            page_num = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as e:
                log(f"  page {page_num}: validation failed ({e})")
                continue
            validated[page_num] = result
            if done % 20 == 0 or done == len(futures):
                log(f"  validated {done}/{len(futures)} pages")
    return validated


# ── Stage 4: batched MEITY-empanelled LLM validation (for the "needs LLM" bucket) ─

def build_batch_validation_prompt(pages: List[int], pages_grouped: Dict[int, List[Dict[str, Any]]],
                                   page_text: Dict[int, str]) -> str:
    page_sections = []
    for page_num in pages:
        candidates = dedupe_candidates_by_bbox(pages_grouped.get(page_num, []))
        ruled_n = len(_distinct_ruled_candidates(candidates))
        sections = [f"  --- {t['method']}, table {i + 1} ---\n{df_to_text(t['df'], max_rows=40)}" for i, t in enumerate(candidates)]
        text = page_text.get(page_num, "")[:RAW_TEXT_CHARS_PER_PAGE_BATCHED]
        count_hint = (
            f"\nRuled-border detectors found {ruled_n} distinct table region(s). "
            f"Return exactly {ruled_n} table object(s) for this page unless raw text clearly shows otherwise."
            if ruled_n else ""
        )
        page_sections.append(
            f"=== PAGE {page_num} ===\n"
            f"Raw page text:\n{text}\n\n"
            f"Extracted candidates:\n{chr(10).join(sections) if sections else '  (no table candidates extracted on this page)'}"
            f"{count_hint}"
        )

    page_sections_block = chr(10).join(
        "----------------------------------------" + chr(10) + s for s in page_sections
    )
    return pdf_batch_validation_user_prompt(
        page_numbers=pages,
        page_sections_block=page_sections_block,
    )


def validate_batch(client: openai.OpenAI, pages: List[int], pages_grouped: Dict[int, List[Dict[str, Any]]],
                    page_text: Dict[int, str]) -> Dict[int, Dict[str, Any]]:
    prompt = build_batch_validation_prompt(pages, pages_grouped, page_text)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=min(
            BATCH_VALIDATION_MAX_TOKENS_CAP, MAX_TOKENS_PER_PAGE * len(pages)
        ),
        temperature=LLM_VALIDATION_TEMPERATURE,
    )
    text_out = resp.choices[0].message.content
    try:
        parsed = json.loads(text_out)
    except json.JSONDecodeError:
        cleaned = re.sub(r"```[a-z]*\n?", "", text_out).strip().rstrip("`")
        parsed = json.loads(cleaned)

    by_page = parsed.get("pages", {})
    # ADDED: pass per-page pymupdf candidates + page text into stamp so
    # ungrounded Direction columns can be stripped and alignment guard can
    # fall back when the LLM grid is shifted.
    return {
        p: _stamp_llm_metadata(
            by_page.get(str(p), {"tables": []}),
            p,
            pages_grouped.get(p),
            page_text.get(p, ""),
        )
        for p in pages
    }


def validate_all_pages_batched(pages_grouped: Dict[int, List[Dict[str, Any]]], page_text: Dict[int, str],
                                batch_size: int = BATCH_SIZE, n_workers: int = OPENAI_WORKERS,
                                progress_cb: Optional[Callable[[int, int], None]] = None,
                                api_key: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    key = (api_key or "").strip()
    if not key:
        return {}
    client = openai.OpenAI(api_key=key)
    all_pages = list(pages_grouped.keys())
    batches = [all_pages[i:i + batch_size] for i in range(0, len(all_pages), batch_size)]

    validated: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(validate_batch, client, batch, pages_grouped, page_text): batch for batch in batches}
        done_pages = 0
        for future in as_completed(futures):
            batch = futures[future]
            try:
                result = future.result()
            except Exception as e:
                log(f"  batch {batch[0]}-{batch[-1]} failed, falling back to per-page ({e})")
                for page_num in batch:
                    try:
                        result_single = validate_page(client, page_num, pages_grouped[page_num], page_text.get(page_num, ""))
                        # ADDED: pass candidates + page text for Direction strip / alignment guard.
                        validated[page_num] = _stamp_llm_metadata(
                            result_single,
                            page_num,
                            pages_grouped.get(page_num),
                            page_text.get(page_num, ""),
                        )
                    except Exception as e2:
                        log(f"    page {page_num}: per-page fallback also failed ({e2})")
                done_pages += len(batch)
                log(f"  validated {done_pages}/{len(all_pages)} pages")
                if progress_cb:
                    progress_cb(done_pages, len(all_pages))
                continue
            validated.update(result)
            done_pages += len(batch)
            log(f"  validated {done_pages}/{len(all_pages)} pages ({len(batches)} batches of ~{batch_size})")
            if progress_cb:
                progress_cb(done_pages, len(all_pages))
    return validated


def _log_representative_examples(llm_results: Dict[int, Dict[str, Any]], high_results: Dict[int, Dict[str, Any]]) -> None:
    """Logs up to three examples for a quick sanity check: one table that
    needs no review, one flagged for semantic classification uncertainty,
    one flagged for data reconstruction uncertainty (uncertain_cells). Not
    every run will have all three -- e.g. a small page range might not
    contain an uncertain_cells case -- so each is best-effort."""

    def _describe(page_num: int, t: Dict[str, Any], why: str) -> None:
        log(f"  example ({why}) -- page {page_num}: title={t.get('title')!r}")
        log(f"    human_review_needed={t.get('human_review_needed')}, human_review_reason={t.get('human_review_reason')!r}")
        log(f"    semantic_status={t.get('semantic_status')}, extraction={t.get('extraction')}, uncertain_cells={t.get('uncertain_cells')}")
        cls = t.get("classification") or {}
        flagged_fields = [(name, f.get("human_review_reason")) for name, f in cls.items()
                          if isinstance(f, dict) and f.get("human_review_needed")]
        log(f"    classification fields flagged for review: {flagged_fields or 'none'}")
        for col in t.get("columns", [])[:4]:
            log(f"    column {col.get('name')!r}: role={col.get('role')}, concept={col.get('concept')}, "
                f"human_review_needed={col.get('human_review_needed')}, human_review_reason={col.get('human_review_reason')!r}")

    no_review = semantic_review = extraction_review = None
    for page_num, result in llm_results.items():
        for t in result.get("tables", []):
            if not no_review and not t.get("human_review_needed"):
                no_review = (page_num, t)
            if not extraction_review and t.get("uncertain_cells"):
                extraction_review = (page_num, t)
            if not semantic_review and t.get("human_review_needed") and not t.get("uncertain_cells"):
                semantic_review = (page_num, t)

    if no_review:
        _describe(*no_review, why="no review needed")
    if semantic_review:
        _describe(*semantic_review, why="semantic classification uncertainty")
    if extraction_review:
        _describe(*extraction_review, why="data reconstruction uncertainty")
    if not (no_review or semantic_review or extraction_review):
        log("  (no LLM-classified tables to show examples from)")
