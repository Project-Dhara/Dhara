"""Heuristic accept when LLM is unavailable or empty."""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymupdf

from app.services.extraction.pdf.confidence_validation.confidence_split import (
    _ruled_tables_from_candidates,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import (
    extract_page_text_blocks,
)
from app.services.extraction.pdf.utils.pymupdf import log
from app.services.llm_prompts import resolve_cpu_workers


def _heuristic_accept_chunk(
    items: List[Tuple[int, List[Dict[str, Any]]]],
    page_text: Dict[int, str],
    outline_index: Dict[int, List[str]],
    pdf_path: Optional[str],
    review_reason: str,
) -> Dict[int, Dict[str, Any]]:
    """Accept one chunk of pages; each thread opens its own PDF."""
    out: Dict[int, Dict[str, Any]] = {}
    doc = None
    if pdf_path and Path(pdf_path).is_file():
        doc = pymupdf.open(pdf_path)
    try:
        for page_num, candidates in items:
            page_blocks = (
                extract_page_text_blocks(doc, page_num) if doc is not None else None
            )
            tables = _ruled_tables_from_candidates(
                candidates,
                page_num=page_num,
                page_text=page_text.get(page_num, ""),
                page_blocks=page_blocks,
                outline_sections=outline_index.get(page_num, []),
                force_review=True,
                review_reason=review_reason,
            )
            out[page_num] = {"tables": tables}
    finally:
        if doc is not None:
            doc.close()
    return out


def heuristic_accept_pages(
    pages_grouped: Dict[int, List[Dict[str, Any]]],
    page_text: Optional[Dict[int, str]] = None,
    *,
    pdf_path: Optional[Path] = None,
    outline_index: Optional[Dict[int, List[str]]] = None,
    review_reason: str = "no_llm_key_heuristic",
) -> Dict[int, Dict[str, Any]]:
    """Accept LLM-bucket pages via PyMuPDF heuristics when no MEITY key is set."""
    page_text = page_text or {}
    outline_index = outline_index or {}
    items = list(pages_grouped.items())
    if not items:
        return {}

    pdf_path_str = str(pdf_path) if pdf_path and Path(pdf_path).is_file() else None
    n_workers = min(resolve_cpu_workers(), len(items))
    if n_workers <= 1:
        return _heuristic_accept_chunk(
            items, page_text, outline_index, pdf_path_str, review_reason
        )

    chunks: List[List[Tuple[int, List[Dict[str, Any]]]]] = [[] for _ in range(n_workers)]
    for i, item in enumerate(items):
        chunks[i % n_workers].append(item)
    chunks = [c for c in chunks if c]

    out: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
        futures = [
            pool.submit(
                _heuristic_accept_chunk,
                chunk,
                page_text,
                outline_index,
                pdf_path_str,
                review_reason,
            )
            for chunk in chunks
        ]
        for future in as_completed(futures):
            out.update(future.result())
    return out
