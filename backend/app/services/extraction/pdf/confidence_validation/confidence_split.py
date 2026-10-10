"""Confidence routing: high vs needs-LLM buckets."""
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

from app.services.extraction.pdf.confidence_validation.table_confidence import (
    classify_page,
    extract_page_text_blocks,
    table_dict_from_df,
)
from app.services.extraction.pdf.utils.pymupdf import (
    _bboxes_same_table,
    dedupe_candidates_by_bbox,
    log,
)

def split_by_confidence(
    pages_grouped: Dict[int, List[Dict[str, Any]]],
    page_text: Optional[Dict[int, str]] = None,
    *,
    pdf_path: Optional[Path] = None,
    outline_index: Optional[Dict[int, List[str]]] = None,
):
    """Runs the deterministic (no-LLM) classifier per page. Returns:
      high_results   -- {page_num: {"tables": [...]}} accepted directly, no LLM
      llm_pages      -- {page_num: candidates} still needing the OpenAI step
      reason_counts  -- {reason: count} for the "llm" bucket, for visibility into why

    For high-confidence pages, titles are inferred from page_text, positioned
    text above the table bbox, extended caption patterns, and PDF outline —
    see pdf_table_confidence.infer_title_from_page_text.
    """
    page_text = page_text or {}
    outline_index = outline_index or {}
    high_results: Dict[int, Dict[str, Any]] = {}
    llm_pages: Dict[int, List[Dict[str, Any]]] = {}
    reason_counts: Dict[str, int] = {}

    doc = None
    if pdf_path and Path(pdf_path).is_file():
        doc = pymupdf.open(pdf_path)
    page_blocks_cache: Dict[int, List[Dict[str, float]]] = {}

    try:
        for page_num, candidates in pages_grouped.items():
            # Collapse lines_strict/lines/text clones of the same bbox before
            # classifying or sending to the LLM (avoids mix-and-match).
            candidates = dedupe_candidates_by_bbox(candidates)
            bucket, reason, _info = classify_page(candidates)
            if bucket == "high":
                if doc is not None and page_num not in page_blocks_cache:
                    page_blocks_cache[page_num] = extract_page_text_blocks(doc, page_num)
                page_blocks = page_blocks_cache.get(page_num)
                outline_sections = outline_index.get(page_num, [])
                tables = _ruled_tables_from_candidates(
                    candidates,
                    page_num=page_num,
                    page_text=page_text.get(page_num, ""),
                    page_blocks=page_blocks,
                    outline_sections=outline_sections,
                )
                high_results[page_num] = {"tables": tables}
            else:
                llm_pages[page_num] = candidates
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
    finally:
        if doc is not None:
            doc.close()

    return high_results, llm_pages, reason_counts


# ── Stage 3: MEITY-empanelled LLM validation / restructuring ─────────────

def df_to_text(df: pd.DataFrame, max_rows: int = 40) -> str:
    return df.head(max_rows).to_csv(index=False, header=False)


def _ruled_tables_from_candidates(
    candidates: List[Dict[str, Any]],
    *,
    page_num: int,
    page_text: str = "",
    page_blocks: Optional[List[Dict[str, float]]] = None,
    outline_sections: Optional[List[str]] = None,
    force_review: bool = False,
    review_reason: str = "heuristic_no_llm",
) -> List[Dict[str, Any]]:
    """Build table dicts from ruled-border candidates (no LLM)."""
    candidates = dedupe_candidates_by_bbox(list(candidates or []))
    spreadsheet = {c.get("method") for c in candidates} & {"excel_grid", "csv_grid"}
    if spreadsheet:
        ruled_methods = spreadsheet
        ordered = [c for c in candidates if c.get("method") in ruled_methods]
    else:
        has_strict = any(c.get("method") == "pymupdf_lines_strict" for c in candidates)
        ruled_methods = {"pymupdf_lines_strict"} if has_strict else {"pymupdf_lines"}
        ordered = [
            c for c in candidates
            if c.get("method") in ruled_methods
        ] + (
            [c for c in candidates if c.get("method") == "pymupdf_lines"]
            if has_strict else []
        )
    tables: List[Dict[str, Any]] = []
    taken_bboxes: List[List[float]] = []
    seen: set = set()
    for c in ordered:
        cid = id(c)
        if cid in seen:
            continue
        seen.add(cid)
        df = c.get("df")
        if df is None or getattr(df, "empty", True):
            continue
        bb = c.get("bbox")
        if bb and any(_bboxes_same_table(bb, prev) for prev in taken_bboxes):
            continue
        bbox_f = None
        if bb and len(bb) >= 4:
            bbox_f = [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])]
        table = table_dict_from_df(
            df,
            page_text=page_text,
            page_num=page_num,
            method=str(c.get("method") or "pymupdf_lines_strict"),
            bbox=bbox_f,
            page_blocks=page_blocks,
            outline_sections=outline_sections,
        )
        table["page"] = page_num
        if c.get("sheet"):
            table["sheet"] = c.get("sheet")
        if c.get("source_file"):
            table["source_file"] = c.get("source_file")
        if bbox_f:
            table["bbox"] = bbox_f
        if force_review:
            table["human_review_needed"] = True
            table["human_review_reason"] = review_reason
            table["semantic_status"] = "not_classified"
            table["extraction"] = {
                "method": str(c.get("method") or "pymupdf_lines_strict"),
                "confidence": "heuristic_no_llm",
            }
        tables.append(table)
        if bb:
            taken_bboxes.append(bb)
    return tables


def _llm_pages_missing_tables(
    llm_pages: Dict[int, List[Dict[str, Any]]],
    llm_results: Dict[int, Dict[str, Any]],
) -> Dict[int, List[Dict[str, Any]]]:
    """Pages that still need a ruled-grid accept after LLM validation failed/empty.

    When the MEITY key is present but invalid/quota-exhausted, validate_* logs
    failures and omits those pages — without this fallback the extracted tables
    are silently dropped.
    """
    missing: Dict[int, List[Dict[str, Any]]] = {}
    for page_num, cands in (llm_pages or {}).items():
        if not cands:
            continue
        result = (llm_results or {}).get(page_num)
        tables = result.get("tables") if isinstance(result, dict) else None
        if not tables:
            missing[page_num] = cands
    return missing
