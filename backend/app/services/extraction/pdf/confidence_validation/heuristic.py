"""Heuristic accept when LLM is unavailable or empty."""
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
    _ruled_tables_from_candidates,
)
from app.services.extraction.pdf.confidence_validation.table_confidence import (
    extract_page_text_blocks,
)
from app.services.extraction.pdf.utils.pymupdf import log

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
    out: Dict[int, Dict[str, Any]] = {}
    doc = None
    if pdf_path and Path(pdf_path).is_file():
        doc = pymupdf.open(pdf_path)
    try:
        for page_num, candidates in pages_grouped.items():
            page_blocks = None
            if doc is not None:
                page_blocks = extract_page_text_blocks(doc, page_num)
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
