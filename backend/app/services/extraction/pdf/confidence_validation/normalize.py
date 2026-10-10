"""Table / field normalization and human-review rollup."""
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

from app.services.extraction.pdf.confidence_validation.constants import (
    CLASSIFICATION_FIELDS,
    REVIEW_REASONS,
    _REASON_PRIORITY,
)
from app.services.extraction.pdf.utils.header_utils import (
    _is_descriptive_in_grid_title,
    _is_table_id_only,
    extract_in_grid_caption,
)
from app.services.extraction.pdf.utils.pymupdf import _best_matching_ruled_candidate
from app.services.extraction.pdf.confidence_validation.table_confidence import (
    strip_caption_label_prefix,
    title_needs_review,
)

def _coerce_reason(raw: Any) -> Optional[str]:
    """Validates a human_review_reason against REVIEW_REASONS. If the model
    returned something close but non-standard, infer the nearest standard
    reason by keyword; if nothing matches, return None so the caller can
    degrade that flag to "no review needed" rather than surface an
    unexplained, unactionable flag."""
    if raw in REVIEW_REASONS:
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.lower()
    if "garbl" in s or "corrupt" in s or "encoding" in s or "mojibake" in s:
        return "garbled_extracted_value"
    # ADDED: map free-text alignment wording to the new standard reason.
    if "align" in s or "mismatch" in s or "shifted" in s or "wrong column" in s:
        return "column_alignment_mismatch"
    if "conflict" in s or "disagree" in s:
        return "conflicting_extraction"
    if "role" in s:
        return "uncertain_semantic_role"
    if "concept" in s or "meaning" in s:
        return "uncertain_concept"
    if "extraction" in s or "extract" in s:
        return "uncertain_extraction"
    if "ambig" in s:
        return "ambiguous_column"
    if "title" in s:
        return "uncertain_title"
    return None


def _normalize_review_flag(human_review_needed: Any, human_review_reason: Any) -> tuple[bool, Optional[str]]:
    """Normalizes one (human_review_needed, human_review_reason) pair.
    human_review_needed=false always forces reason to null. A true flag
    without a reason we can validate/infer is NOT trusted as-is -- an
    unexplained review flag isn't actionable for the frontend, so it's
    downgraded to (false, null) rather than passed through."""
    if not human_review_needed:
        return False, None
    reason = _coerce_reason(human_review_reason)
    if reason is None:
        return False, None
    return True, reason


def _normalize_input_ui(needed: bool, input_type: Any, input_options: Any) -> tuple[Optional[str], Optional[List[str]]]:
    """Keeps LLM input_type / input_options only when review is needed."""
    if not needed:
        return None, None
    kind = str(input_type or "").strip().lower()
    if kind in ("dropdown", "select"):
        opts = input_options if isinstance(input_options, list) else None
        cleaned = [str(o) for o in (opts or []) if o is not None and str(o).strip()]
        return "dropdown", cleaned or None
    if kind in ("inputbox", "input", "text", "textbox"):
        return "inputbox", None
    return "inputbox", None


def _normalize_field(field: Any) -> Dict[str, Any]:
    """Normalizes one classification field to {"value", "human_review_needed",
    "input_type", "input_options", "human_review_reason"}. Tolerates the model
    returning a bare scalar instead of the object shape (treated as the value,
    no review flag) or omitting the field entirely (defaults null/false/null)."""
    if isinstance(field, dict):
        needed, reason = _normalize_review_flag(field.get("human_review_needed", False), field.get("human_review_reason"))
        input_type, input_options = _normalize_input_ui(needed, field.get("input_type"), field.get("input_options"))
        return {
            "value": field.get("value"),
            "human_review_needed": needed,
            "input_type": input_type,
            "input_options": input_options,
            "human_review_reason": reason,
        }
    # Bare scalar (string/null) instead of the object shape -- keep the value.
    return {
        "value": field,
        "human_review_needed": False,
        "input_type": None,
        "input_options": None,
        "human_review_reason": None,
    }


def _llm_title_is_id_only(title: Optional[str]) -> bool:
    """True when title is missing or only a TABLE/STATEMENT-style id label."""
    s = (title or "").strip()
    if not s:
        return True
    if _is_table_id_only(s):
        return True
    # strip_caption_label_prefix leaves a short token like "B-22" for id-only titles.
    stripped = (strip_caption_label_prefix(s) or "").strip()
    if stripped and stripped.lower() != s.lower() and _is_descriptive_in_grid_title(stripped):
        return False
    if stripped and len(stripped) < 18 and _is_table_id_only(s):
        return True
    return False


def _prefer_descriptive_llm_title(
    table: Dict[str, Any],
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """For AI-classified tables only: prefer a descriptive in-grid caption over
    short ids like ``TABLE: B-22``. Does not change PDF extraction heuristics —
    only post-processes LLM title / notes after reconstruction.
    """
    title = (table.get("title") or "").strip() or None

    # Combined "TABLE 2.1: Live births…" → keep the descriptive remainder.
    if title and not _is_table_id_only(title):
        stripped = strip_caption_label_prefix(title)
        if stripped and stripped != title:
            table["title"] = stripped
            table["title_source"] = table.get("title_source") or "llm_stripped_caption_label"
        return table

    if title and not _llm_title_is_id_only(title):
        return table

    replacement: Optional[str] = None
    banner_id: Optional[str] = None
    source: Optional[str] = None

    matched = None
    if candidates:
        matched, _ = _best_matching_ruled_candidate(table, candidates, set())

    seen_dfs: set = set()
    for cand in ([matched] if matched else []) + list(candidates or []):
        if not cand:
            continue
        df = cand.get("df")
        if df is None:
            continue
        df_id = id(df)
        if df_id in seen_dfs:
            continue
        seen_dfs.add(df_id)
        attrs = getattr(df, "attrs", None) or {}
        cap = (attrs.get("dhara_table_caption") or "").strip()
        if not cap or _is_table_id_only(cap):
            continue
        replacement = strip_caption_label_prefix(cap) or cap
        banner_id = (attrs.get("dhara_banner_table_id") or "").strip() or None
        source = "llm_in_grid_caption_from_candidate"
        break

    if not replacement:
        cap_info = extract_in_grid_caption(table.get("rows") or [])
        cap_title = (cap_info.get("title") or "").strip()
        if cap_title and not _is_table_id_only(cap_title):
            replacement = strip_caption_label_prefix(cap_title) or cap_title
            banner_id = (cap_info.get("table_id_label") or "").strip() or banner_id
            source = "llm_in_grid_caption_from_rows"

    if not replacement:
        return table

    if title and _is_table_id_only(title):
        notes = list(table.get("notes") or [])
        note = f"table_id: {title}"
        if note not in notes:
            notes.append(note)
        table["notes"] = notes
        if not banner_id:
            banner_id = title

    table["title"] = replacement
    table["title_source"] = source
    if banner_id:
        table["banner_table_id"] = banner_id
    return table


def _normalize_table(table: Dict[str, Any]) -> Dict[str, Any]:
    """Fills in defaults for any optional field the LLM omitted or returned
    in an unexpected shape, so a malformed/partial response degrades
    gracefully (null/"unknown"/false) instead of crashing the batch or
    leaving downstream consumers to KeyError on a missing field."""
    cls = table.get("classification")
    cls = cls if isinstance(cls, dict) else {}

    columns = []
    for c in table.get("columns") or []:
        if isinstance(c, str):
            # Model ignored the object schema and returned a bare name -- keep
            # the name, mark everything else unknown rather than dropping it.
            columns.append({
                "name": c, "role": "unknown", "concept": None, "description": None,
                "data_type": "unknown", "unit": None, "category": None,
                "human_review_needed": False, "input_type": None, "input_options": None,
                "human_review_reason": None,
            })
        elif isinstance(c, dict):
            needed, reason = _normalize_review_flag(c.get("human_review_needed", False), c.get("human_review_reason"))
            input_type, input_options = _normalize_input_ui(needed, c.get("input_type"), c.get("input_options"))
            # Direction-like columns: default to up/down dropdown when the model
            # flagged review but omitted input_type / options.
            name_l = str(c.get("name") or "").lower()
            concept_l = str(c.get("concept") or "").lower()
            if needed and input_type is None and any(
                k in name_l or k in concept_l for k in ("direction", "trend", "change")
            ):
                input_type, input_options = "dropdown", ["up", "down"]
            # Preserve multi-level header meta when present (alignment-guard
            # fallback / post-stamp attach). Do not invent it here.
            header_group = c.get("header_group")
            if header_group is not None:
                header_group = str(header_group).strip() or None
            raw_path = c.get("header_path")
            header_path = None
            if isinstance(raw_path, (list, tuple)):
                header_path = [str(p).strip() for p in raw_path if str(p).strip()]
            col_out = {
                "name": c.get("name", ""),
                "role": c.get("role") or "unknown",
                "concept": c.get("concept"),
                "description": c.get("description"),
                "data_type": c.get("data_type") or "unknown",
                "unit": c.get("unit"),
                "category": c.get("category"),
                "human_review_needed": needed,
                "input_type": input_type,
                "input_options": input_options,
                "human_review_reason": reason,
            }
            if header_path:
                col_out["header_path"] = header_path
                col_out["header_group"] = header_group or (
                    header_path[-2] if len(header_path) >= 2 else None
                )
            elif header_group:
                col_out["header_group"] = header_group
            columns.append(col_out)

    # Pad / trim every row to match column count. The model often declares a
    # Direction/Trend column but omits that cell from each row array, which
    # leaves the UI with a header and no bordered cells underneath.
    ncols = len(columns)
    rows: List[List[Any]] = []
    for raw in table.get("rows") or []:
        if not isinstance(raw, list):
            rows.append([None] * ncols)
            continue
        row = list(raw[:ncols])
        while len(row) < ncols:
            row.append(None)
        rows.append(row)

    columns = dedupe_column_names(columns)

    return {
        "title": table.get("title"),
        "description": table.get("description"),
        "classification": {field: _normalize_field(cls.get(field)) for field in CLASSIFICATION_FIELDS},
        "columns": columns,
        "rows": rows,
        "notes": table.get("notes") or [],
        "uncertain_cells": table.get("uncertain_cells") or [],
    }


def derive_human_review_needed(table: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Computes the FINAL table-level (human_review_needed, human_review_reason)
    deterministically from explicit signals -- never trusts an LLM-provided
    table-level flag directly (the prompt is told not to emit one at all).

    Two different kinds of uncertainty feed into this, kept conceptually
    separate but both able to trigger the table-level flag:
      - data reconstruction uncertainty -> uncertain_cells non-empty, or a
        row value that looks corrupted/mojibake (garbled_extracted_value),
        or ADDED column_alignment_mismatch from the post-LLM grid guard
      - semantic classification uncertainty -> a classification field or
        column marked human_review_needed=true (each keeping its own
        reason), or a column whose role genuinely couldn't be determined
        (role == "unknown" -> uncertain_semantic_role, material to
        understanding the table regardless of whether the model itself
        flagged it)
      - missing / unusable title -> uncertain_title (also applies on the
        deterministic no-LLM path so Preview's Review needed filter sees it)

    When multiple reasons are present, REVIEW_REASONS' order picks ONE for
    the table-level rollup -- the underlying field/column reasons are left
    untouched, so the frontend can still show exactly which field or column
    needs attention and why.

    Tables that simply haven't been semantically classified yet (the
    deterministic high-confidence/no-LLM path) are NOT "needing review" for
    classification -- that status is tracked separately via semantic_status.
    Absence of optional metadata (frequency/unit/description unknown) does
    not, by itself, trigger review either -- see the prompt's
    human_review_needed rules for why the model is told not to flag those.
    A missing table title is the exception: stewards must supply one before
    grouping."""
    reasons_present: set = set()

    if title_needs_review(table.get("title"), table.get("columns") or []):
        reasons_present.add("uncertain_title")

    if table.get("semantic_status") != "classified":
        # Auto-accepted path: only surface missing-title review.
        if "uncertain_title" in reasons_present:
            return True, "uncertain_title"
        return False, None

    uncertain_cells = table.get("uncertain_cells") or []
    rows = table.get("rows") or []
    if uncertain_cells:
        if any(_uncertain_note_is_alignment_mismatch(note) for note in uncertain_cells):
            # Notes written by _apply_column_alignment_guard (legacy + human wording).
            reasons_present.add("column_alignment_mismatch")
        if any(_looks_garbled(note) for note in uncertain_cells) or _rows_look_garbled(rows):
            reasons_present.add("garbled_extracted_value")
        elif any(
            " vs " in str(note) and not _uncertain_note_is_alignment_mismatch(note)
            for note in uncertain_cells
        ):
            # Matches this pipeline's own uncertain_cells note format (see
            # TASK_A_RECONSTRUCTION_RULES / uncertain_cells example) --
            # "row X, col Y: candidateA=... vs candidateB=...".
            # Alignment-guard notes are excluded so fill-rate comparisons are
            # not misread as cell conflicts.
            reasons_present.add("conflicting_extraction")
        elif "column_alignment_mismatch" not in reasons_present:
            reasons_present.add("uncertain_extraction")
    elif _rows_look_garbled(rows):
        # Garbled values can show up even without an explicit uncertain_cells
        # note, e.g. a private-use-area glyph both candidates agreed on.
        reasons_present.add("garbled_extracted_value")

    classification = table.get("classification") or {}
    for f in classification.values():
        if isinstance(f, dict) and f.get("human_review_needed") and f.get("human_review_reason"):
            reasons_present.add(f["human_review_reason"])

    for col in table.get("columns", []):
        if col.get("human_review_needed") and col.get("human_review_reason"):
            reasons_present.add(col["human_review_reason"])
        if col.get("role") == "unknown":
            reasons_present.add("uncertain_semantic_role")

    if not reasons_present:
        return False, None

    reason = min(reasons_present, key=lambda r: _REASON_PRIORITY.get(r, len(REVIEW_REASONS)))
    return True, reason
