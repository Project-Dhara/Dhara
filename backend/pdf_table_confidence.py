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


def table_dict_from_df(df: pd.DataFrame) -> Dict[str, Any]:
    """Build a validated-table-shaped dict directly from a clean DataFrame,
    with no LLM involved. Title/description and all semantic classification
    fields are left null -- this is the fast path specifically because it
    skips the judgment calls (reading surrounding text for a title,
    inferring what a column means) that require an LLM. Schema matches what
    the LLM path produces (see build_validation_prompt/build_batch_
    validation_prompt in sda_india_pdf_extraction.py) so downstream
    consumers (frontend review) can treat both uniformly, keyed off
    "semantic_status" to know whether classification has actually run."""
    cleaned = clean_dataframe_light(df)
    columns = [
        {
            "name": str(c),
            "role": "unknown",
            "concept": None,
            "description": None,
            "data_type": "unknown",
            "unit": None,
            "category": None,
            "human_review_needed": False,
            "human_review_reason": None,
        }
        for c in cleaned.columns
    ]
    empty_field = {"value": None, "human_review_needed": False, "human_review_reason": None}
    return {
        "title": None,
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
