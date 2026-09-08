"""
Deterministic (no-LLM) confidence scoring for extracted table candidates.

The OpenAI validation step in sda_india_pdf_extraction.py is doing real
reconstruction work for some pages (mangled/transposed cells, headers glued
into the first data row, or a page where one detection strategy found
nothing at all) -- see the false-positive investigation earlier in this
pipeline's development for concrete examples. But plenty of pages are
already clean: a well-formed single-header table that both pymupdf
strategies ("lines_strict" and "text") independently agree on doesn't need
an LLM to tell us it's fine.

This module computes cheap structural signals per candidate and classifies
each page as:
  - "high"  -- accept the lines_strict candidate directly, no LLM call.
  - "llm"   -- send to the (batched) OpenAI validation step, same as before.

Originally this gated "high" on the "text" strategy candidate agreeing with
"lines_strict" (two independent tools converging = trustworthy). That
turned out not to work on this PDF: measured across real pages, agreement
ratios were ~0.0 not because cell values conflicted but because the two
strategies extract *differently-scoped* regions of the page -- e.g. shapes
like (12, 2) vs (57, 9) on the same page, where "text" pulled in
surrounding paragraph content well beyond the ruled table's boundaries.
Position-aligned comparison between two differently-bounded grids isn't a
meaningful check, so every real table ended up flagged as "disagreement."

Classification is therefore based on the lines_strict candidate's own
internal structural consistency instead: fill rate, clean single-row
header, and per-column type consistency (a real data column should be
either mostly-numeric or mostly-text, not a murky mix -- a column stuck in
the middle usually means misaligned/corrupted extraction). The "text"
candidate is no longer used as a gate at all. This is weaker evidence than
genuine cross-tool corroboration would have been -- it can't catch a
plausible-looking table with a subtly wrong number -- which is the real
trade-off of skipping the LLM: worth knowing, not just a footnote.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

MIN_ROWS = 2
MIN_NONEMPTY_RATIO = 0.5
MIXED_TYPE_LOW = 0.2
MIXED_TYPE_HIGH = 0.8


def _cell_str(v: Any) -> str:
    return "" if v is None else re.sub(r"\s+", " ", str(v)).strip()


def _is_numeric_cell(v: str) -> bool:
    s = v.replace(",", "").rstrip("%").strip()
    if not s or s in {"-", "—", "NA", "N/A"}:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def clean_dataframe_light(df: pd.DataFrame) -> pd.DataFrame:
    """Whitespace-normalize cells, blank out empty strings, drop fully-empty
    rows/columns. Pure Python cleanup -- no LLM, no restructuring."""
    cleaned = df.map(lambda v: _cell_str(v) or None)
    cleaned.columns = [_cell_str(c) or f"Col_{i + 1}" for i, c in enumerate(cleaned.columns)]
    cleaned = cleaned.dropna(axis=0, how="all").dropna(axis=1, how="all")
    return cleaned.reset_index(drop=True)


def profile_table(df: pd.DataFrame) -> Dict[str, Any]:
    n_rows, n_cols = df.shape
    all_cells = [_cell_str(v) for row in df.values for v in row]
    nonempty = [c for c in all_cells if c]
    nonempty_ratio = (len(nonempty) / len(all_cells)) if all_cells else 0.0

    columns = [str(c) for c in df.columns]
    header_has_multiline = any("\n" in c for c in columns)
    seen: set = set()
    duplicate_columns = False
    for c in columns:
        key = c.strip().lower()
        if key and key in seen:
            duplicate_columns = True
        seen.add(key)

    header_dupe_in_first_row = False
    if n_rows >= 1:
        first_row_vals = {_cell_str(v).lower() for v in df.iloc[0].values if _cell_str(v)}
        col_vals = {c.strip().lower() for c in columns if c.strip()}
        if col_vals:
            overlap = len(first_row_vals & col_vals) / len(col_vals)
            header_dupe_in_first_row = overlap >= 0.5

    # A real data column should be either mostly-numeric (a measurement) or
    # mostly-text (a label) -- not a murky middle. A column stuck between
    # MIXED_TYPE_LOW and MIXED_TYPE_HIGH numeric fraction usually means cells
    # bled into the wrong column during extraction.
    mixed_type_columns = 0
    for col in df.columns:
        vals = [_cell_str(v) for v in df[col].values]
        nonempty = [v for v in vals if v]
        if len(nonempty) < 3:
            continue
        numeric_frac = sum(_is_numeric_cell(v) for v in nonempty) / len(nonempty)
        if MIXED_TYPE_LOW < numeric_frac < MIXED_TYPE_HIGH:
            mixed_type_columns += 1

    return {
        "n_rows": n_rows,
        "n_cols": n_cols,
        "nonempty_ratio": round(nonempty_ratio, 3),
        "header_has_multiline": header_has_multiline,
        "duplicate_columns": duplicate_columns,
        "header_dupe_in_first_row": header_dupe_in_first_row,
        "mixed_type_columns": mixed_type_columns,
    }


def classify_page(candidates: List[Dict[str, Any]]) -> Tuple[str, str, Dict[str, Any]]:
    """Returns (bucket, reason, info). bucket is "high" or "llm"."""
    lines_strict = [c for c in candidates if c["method"] == "pymupdf_lines_strict"]

    if not lines_strict:
        return "llm", "no lines_strict candidate (should not happen post-filter)", {}

    primary = clean_dataframe_light(lines_strict[0]["df"])
    info = profile_table(primary)

    if info["n_rows"] < MIN_ROWS or info["nonempty_ratio"] < MIN_NONEMPTY_RATIO:
        return "llm", "near-empty or sparse lines_strict candidate", info

    if info["header_has_multiline"] or info["duplicate_columns"] or info["header_dupe_in_first_row"]:
        return "llm", "structural issue (multiline/duplicate header or header glued into first row)", info

    if info["mixed_type_columns"] > 0:
        return "llm", "column(s) with a murky numeric/text mix, likely misaligned cells", info

    if any(str(c).startswith("Col_") for c in primary.columns):
        return "llm", "placeholder column header (blank in the raw table) -- real header likely lives outside the ruled region", info

    return "high", "clean single-header table, passes all structural checks", info


# Running headers / chrome on SDA-style index PDFs that should never become
# the table title (they sit above every page, not above one specific table).
_TITLE_CHROME_RE = re.compile(
    r"^(?:"
    r"sdg\s+india\s+index|"
    r"\d{4}\s*[-–—]\s*\d{2,4}|"  # 2023-24
    r"page\s+\d+|"
    r"goal\s+\d+(\.\d+)*|"
    r"www\.|"
    r"https?://"
    r")$",
    re.I,
)
# Explicit "TABLE 2.1: ..." captions — strongest signal when present.
_TABLE_CAPTION_RE = re.compile(
    r"^\s*(TABLE|FIG(?:URE)?|CHART)\s+\d+(?:\.\d+)*\s*[:.\-–—]?\s*(.+)$",
    re.I,
)


def _normalize_title_line(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "").strip())


def _is_chrome_title_line(line: str) -> bool:
    s = _normalize_title_line(line)
    if not s or len(s) < 3:
        return True
    if _TITLE_CHROME_RE.match(s):
        return True
    # Very long paragraph-like lines are body text, not headings.
    if len(s) > 140:
        return True
    return False


def _looks_like_heading(line: str) -> bool:
    """Heuristic: short Title Case / ALL CAPS / few words, not a sentence."""
    s = _normalize_title_line(line)
    if _is_chrome_title_line(s):
        return False
    words = s.split()
    if not (1 <= len(words) <= 12):
        return False
    # Reject lines that look like the table's own column header row.
    if s.count("|") >= 2:
        return False
    # Prefer Title Case / ALL CAPS; allow mixed if short (e.g. "Target Justification").
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    upper_frac = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_frac < 0.2 and not s[:1].isupper():
        return False
    return True


def infer_title_from_page_text(
    page_text: str,
    columns: List[str],
    page_num: Optional[int] = None,
) -> Tuple[Optional[str], str]:
    """
    Infer a display title for an auto-accepted (no-LLM) table from the page's
    plain text. The ruled-table extract only has cell/header values — section
    headings like "Target Justification" live *above* the grid in the PDF, so
    we recover them from page_text instead of calling an LLM.

    Strategy (first match wins):
      1. Explicit TABLE/FIGURE caption on the page (e.g. "TABLE 2.1: …").
      2. Heading-like line immediately above the column-header cue in the text
         (find first column name in page_text, walk upward, skip chrome).
      3. Join the first few column names as a compact fallback.
      4. "Page {n} table" last resort.

    Returns (title, title_source) where title_source documents which branch
    fired (for Preview/debugging; not an LLM decision).
    """
    col_names = [_normalize_title_line(c) for c in columns if _normalize_title_line(c)]
    lines = [_normalize_title_line(ln) for ln in (page_text or "").splitlines()]
    lines = [ln for ln in lines if ln]

    # --- 1) Explicit TABLE / FIGURE caption anywhere on the page ---
    for ln in lines:
        m = _TABLE_CAPTION_RE.match(ln)
        if m:
            rest = _normalize_title_line(m.group(2))
            # Keep the full caption including "TABLE 2.1: …" when informative.
            title = ln if rest else ln
            if not _is_chrome_title_line(title):
                return title, "heuristic_table_caption"

    # --- 2) Line above the column-header cue ("Indicators", etc.) ---
    # Locate where the table header appears in the text stream, then take the
    # nearest prior heading-like line (skips "SDG INDIA INDEX" / year chrome).
    header_idx = None
    col_lower = {c.lower() for c in col_names[:3] if c}
    for i, ln in enumerate(lines):
        low = ln.lower()
        # Header row often appears as one line or consecutive short labels.
        if col_lower and any(c in low for c in col_lower):
            # Prefer a line that looks like several headers, or the first col alone.
            hits = sum(1 for c in col_lower if c in low)
            if hits >= 1:
                header_idx = i
                break
    if header_idx is not None and header_idx > 0:
        for j in range(header_idx - 1, max(-1, header_idx - 8), -1):
            candidate = lines[j]
            if _looks_like_heading(candidate):
                # Avoid picking a column name itself as the title.
                if candidate.lower() in col_lower:
                    continue
                return candidate, "heuristic_heading_above_table"

    # --- 3) Column-name fallback ---
    if col_names:
        joined = " · ".join(col_names[:4])
        if len(joined) <= 120:
            return joined, "heuristic_column_names"

    # --- 4) Last resort ---
    if page_num is not None:
        return f"Page {page_num} table", "heuristic_page_fallback"
    return None, "heuristic_none"


def table_dict_from_df(
    df: pd.DataFrame,
    *,
    page_text: str = "",
    page_num: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a validated-table-shaped dict directly from a clean DataFrame,
    with no LLM involved. Semantic classification fields stay null (this path
    skips meaning judgment). Title is filled by infer_title_from_page_text
    when page_text is provided — the heading sits outside the ruled grid, so
    a cheap text heuristic replaces an LLM title call. Schema matches the LLM
    path so Preview can treat both uniformly via semantic_status."""
    cleaned = clean_dataframe_light(df)
    col_names = [str(c) for c in cleaned.columns]
    columns = [
        {
            "name": name,
            "role": "unknown",
            "concept": None,
            "description": None,
            "data_type": "unknown",
            "unit": None,
            "category": None,
            "human_review_needed": False,
            "human_review_reason": None,
        }
        for name in col_names
    ]
    title, title_source = infer_title_from_page_text(page_text, col_names, page_num=page_num)
    empty_field = {"value": None, "human_review_needed": False, "human_review_reason": None}
    return {
        "title": title,
        "title_source": title_source,
        "description": None,
        "classification": {
            "domain": dict(empty_field), "subject": dict(empty_field), "entity": dict(empty_field),
            "table_type": dict(empty_field), "geography": dict(empty_field), "time_period": dict(empty_field),
            "frequency": dict(empty_field), "unit": dict(empty_field),
        },
        "columns": columns,
        "rows": [[None if v is None else str(v) for v in row] for row in cleaned.values.tolist()],
        "notes": [],
        "uncertain_cells": [],
        "semantic_status": "not_classified",
        # human_review_needed is always False here, not merely defaulted: this
        # flag means "an existing AI decision needs a human look," and this
        # path has made no semantic decisions at all yet to review -- it is
        # NOT a signal that classification hasn't happened (that's
        # semantic_status's job). See derive_human_review_needed for the
        # equivalent (and only other) place this flag gets computed.
        "human_review_needed": False,
        "human_review_reason": None,
        "extraction": {"method": "pymupdf_lines_strict", "confidence": "high"},
        "source": "auto_high_confidence",
    }
