"""
Run: python sda_india_pdf_extraction.py [--pages N] [--limit N]
"""

import argparse
import json
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import openai
import pandas as pd
import pymupdf
from dotenv import load_dotenv

from pdf_extraction_workers import extract_pymupdf_chunk
from pdf_table_confidence import classify_page, table_dict_from_df

load_dotenv(Path(__file__).parent / ".env")

PDF_PATH = Path(__file__).parent.parent / "SDA_INDIA_0.pdf"
OUTPUT_DIR = Path(__file__).parent / "data" / "sda_india_extraction"

TEXT_MIN_CHARS = 20
CPU_WORKERS = min(os.cpu_count() or 4, 8)
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_WORKERS = 6
BATCH_SIZE = 5
# Bumped from 2500/4000 -> each table's response now also carries a
# "classification" block and per-column role/concept/description/data_type/
# unit/category, not just title+columns+rows -- same single call per
# page/batch, just a fatter response payload.
MAX_TOKENS_PER_PAGE = 3500
SINGLE_PAGE_MAX_TOKENS = 6000
RAW_TEXT_CHARS_PER_PAGE_BATCHED = 1500


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Stage 1: classify pages ──────────────────────────────────────────────

def classify_pages(pdf_path: Path, min_chars: int = TEXT_MIN_CHARS) -> tuple[List[int], Dict[int, str]]:
    doc = pymupdf.open(pdf_path)
    text_pages: List[int] = []
    page_text: Dict[int, str] = {}
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        if len(text.strip()) >= min_chars:
            text_pages.append(i)
            page_text[i] = text
    doc.close()
    return text_pages, page_text


# ── Stage 2: extract tables ──────────────────────────────────────────────

def chunk_list(lst: List[int], n_chunks: int, seed: int = 0) -> List[List[int]]:
    """Shuffle (deterministically) then split into n_chunks contiguous pieces.

    This PDF's expensive-to-parse pages recur at a near-constant spacing
    (~16 pages apart -- one per state/section, presumably). Plain round-robin
    chunking (lst[i::n]) resonates with any such periodic pattern: on one
    real run, 7 of the 8 slowest pages in the whole document all landed on
    the same worker because their positions in the page list all happened to
    share the same remainder mod 8. Shuffling first breaks any alignment
    between a periodic cost pattern and the chunk boundaries, however many
    workers are used."""
    import random

    n_chunks = max(1, min(n_chunks, len(lst)))
    if not lst:
        return []
    shuffled = lst[:]
    random.Random(seed).shuffle(shuffled)
    size = (len(shuffled) + n_chunks - 1) // n_chunks
    return [shuffled[i:i + size] for i in range(0, len(shuffled), size)]


def extract_all_tables(pdf_path: Path, pages: List[int], n_workers: int = CPU_WORKERS,
                        progress_cb: Optional[Callable[[int, int], None]] = None) -> List[Dict[str, Any]]:
    """Runs extract_pymupdf_chunk over `pages` across a process pool.

    If a worker dies (e.g. OOM-killed), ProcessPoolExecutor marks *every*
    pending/in-flight future as failed, not just the chunk that actually
    crashed -- otherwise-healthy workers' results are lost too. So on a
    BrokenProcessPool we retry just the pages that didn't complete, using
    fewer workers (halving each time) to reduce the memory pressure that
    likely caused the crash, instead of silently returning partial tables."""
    total_pages = len(pages)
    all_tables: List[Dict[str, Any]] = []
    remaining = list(pages)
    workers = max(1, n_workers)
    attempt = 0
    max_attempts = 4

    while remaining and attempt < max_attempts:
        attempt += 1
        chunks = chunk_list(remaining, workers)
        if not chunks:
            break

        pool_broke = False
        with ProcessPoolExecutor(max_workers=len(chunks)) as pool:
            futures = {pool.submit(extract_pymupdf_chunk, str(pdf_path), chunk): chunk for chunk in chunks}
            for future in as_completed(futures):
                chunk = futures[future]
                try:
                    all_tables.extend(future.result())
                    remaining = [p for p in remaining if p not in chunk]
                except BrokenProcessPool as e:
                    pool_broke = True
                    log(f"[extract] process pool crashed on chunk {chunk[0]}-{chunk[-1]} "
                        f"(likely OOM): {e}")
                except Exception as e:
                    log(f"[extract] chunk {chunk[0]}-{chunk[-1]} failed: {e}")
                    remaining = [p for p in remaining if p not in chunk]
                if progress_cb:
                    progress_cb(total_pages - len(remaining), total_pages)

        if not remaining:
            break
        if not pool_broke:
            # Per-chunk failures, not a pool crash -- retrying won't help.
            break
        if workers == 1:
            log(f"[extract] process pool crashed with a single worker; giving up on "
                f"{len(remaining)} remaining page(s)")
            break
        workers = max(1, workers // 2)
        log(f"[extract] retrying {len(remaining)} remaining page(s) with {workers} worker(s)")

    return all_tables


def group_by_page(tables: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
    pages: Dict[int, List[Dict[str, Any]]] = {}
    for t in tables:
        pages.setdefault(t["page"], []).append(t)
    return dict(sorted(pages.items()))

def filter_candidate_pages(pages_grouped: Dict[int, List[Dict[str, Any]]]) -> Dict[int, List[Dict[str, Any]]]:
    return {
        page_num: candidates
        for page_num, candidates in pages_grouped.items()
        if any(c["method"] == "pymupdf_lines_strict" for c in candidates)
    }


def split_by_confidence(pages_grouped: Dict[int, List[Dict[str, Any]]]):
    """Runs the deterministic (no-LLM) classifier per page. Returns:
      high_results   -- {page_num: {"tables": [...]}} accepted directly, no LLM
      llm_pages      -- {page_num: candidates} still needing the OpenAI step
      reason_counts  -- {reason: count} for the "llm" bucket, for visibility into why
    """
    high_results: Dict[int, Dict[str, Any]] = {}
    llm_pages: Dict[int, List[Dict[str, Any]]] = {}
    reason_counts: Dict[str, int] = {}

    for page_num, candidates in pages_grouped.items():
        bucket, reason, _info = classify_page(candidates)
        if bucket == "high":
            primary = next(c["df"] for c in candidates if c["method"] == "pymupdf_lines_strict")
            table = table_dict_from_df(primary)
            table["page"] = page_num
            high_results[page_num] = {"tables": [table]}
        else:
            llm_pages[page_num] = candidates
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return high_results, llm_pages, reason_counts


# ── Stage 3: OpenAI validation / restructuring ───────────────────────────

def df_to_text(df: pd.DataFrame, max_rows: int = 40) -> str:
    return df.head(max_rows).to_csv(index=False, header=False)


# Shared across the single-page and batched prompts (build_validation_prompt /
# build_batch_validation_prompt) so the two jobs -- reconstruct, then classify
# -- are worded identically everywhere they're asked for, in one LLM call.
TASK_A_RECONSTRUCTION_RULES = """TASK A -- RECONSTRUCT THE TABLE:
- Reconcile the candidate extractions into ONE clean, correct table per distinct table on the page.
- NEVER invent a value that isn't present in at least one candidate or the raw text.
- Prefer whichever candidate got a given row/column right; you may combine cells from different candidates.
- If candidates disagree on a cell and you can't tell which is right from the raw text, keep the
  pymupdf_lines_strict value (or any single consistent choice) and add a note in "uncertain_cells".
- Flatten multi-row headers into single column names.
- Preserve a title/description if one is visible in the raw text."""

TASK_B_CLASSIFICATION_RULES = """TASK B -- UNDERSTAND THE TABLE (initial semantic classification only):
After reconstructing a table, determine what it appears to mean, using the page text, table title, headers,
extracted values, and any notes/footnotes as context.

At table level, identify where possible: domain, subject, entity, table_type, geography, time_period,
frequency, unit. Each of these is an object: {"value": ..., "human_review_needed": true|false,
"human_review_reason": "..."|null} -- see the human_review_needed rules below.

At column level, for each column identify:
- "role": one of "identifier", "dimension", "measure", "attribute", "unknown"
- "concept": the semantic concept the column represents (e.g. "State", "Population", "Primary Health Centre")
- "description": a short description of the column
- "data_type": one of "string", "integer", "decimal", "date", "boolean", "categorical", "unknown"
- "unit": the unit of measurement if applicable, else null
- "category": a sub-category/grouping value if applicable (e.g. a "Male" column's category is "Male"), else null
- "human_review_needed": true|false, "human_review_reason": "..."|null -- see the rules below

Examples:
- "State" -> role: dimension, concept: State, data_type: categorical, human_review_needed: false, human_review_reason: null
- "PHC ID" -> role: identifier, concept: Primary Health Centre, data_type: string, human_review_needed: false, human_review_reason: null
- "Male" -> role: measure, concept: Population, category: Male, data_type: integer, human_review_needed: false, human_review_reason: null
- "Total" -> role: measure, concept: Population, data_type: integer, human_review_needed: false, human_review_reason: null
- "PHC" (ambiguous abbreviation, could mean several things) -> concept: Primary Health Centre (best guess),
  human_review_needed: true, human_review_reason: "uncertain_concept"

human_review_needed / human_review_reason rules (both for each classification field above, and for each column):
- Give your best semantic interpretation always -- never leave a field empty just because you're unsure;
  put your best guess in "value"/the column fields, and use human_review_needed to flag the uncertainty
  instead of refusing to answer.
- Set human_review_needed=true ONLY when there is MEANINGFUL uncertainty or ambiguity a human should
  resolve -- e.g. a column name/abbreviation that could plausibly mean more than one thing, a table title
  that doesn't clearly indicate its subject, or a role you genuinely can't determine (role: "unknown").
- Do NOT set human_review_needed=true just because an OPTIONAL field is simply not present in the source
  (e.g. frequency or unit legitimately don't apply to this table) -- in that case use value: null,
  human_review_needed: false, human_review_reason: null. Missing-and-not-applicable is not the same as
  uncertain-and-ambiguous.
- When human_review_needed=true, human_review_reason MUST be exactly one of these standardized values
  (do not invent your own wording):
    "uncertain_extraction"    -- the extracted value itself may be wrong, incomplete, or hard to read
    "conflicting_extraction"  -- two extraction candidates disagree and you had to pick one
    "garbled_extracted_value" -- the extracted text contains corrupted/mojibake/encoding-broken characters
    "uncertain_semantic_role" -- you cannot confidently tell what role this column/field plays
    "uncertain_concept"       -- the name/abbreviation could plausibly mean more than one real-world concept
    "ambiguous_column"        -- some other column-level ambiguity not covered by the above
- When human_review_needed=false, human_review_reason MUST be null.
- Also add a brief note in "notes" explaining the uncertainty (e.g. "column 'PHC' -- could be Primary Health
  Centre or another facility type, please confirm").
- Do NOT hallucinate standards, codes, entities, units, or dates that aren't supported by the page.
- Do NOT attempt harmonization, do NOT map to any external standard/code list (e.g. NMDS/LGD/NCO), and do NOT
  group this table with any other table. That happens in a later stage, not here."""

TABLE_SCHEMA_EXAMPLE = """{
  "tables": [
    {
      "title": "...",
      "description": "...",
      "classification": {
        "domain": {"value": "...", "human_review_needed": false, "human_review_reason": null},
        "subject": {"value": "...", "human_review_needed": false, "human_review_reason": null},
        "entity": {"value": "...", "human_review_needed": false, "human_review_reason": null},
        "table_type": {"value": "...", "human_review_needed": false, "human_review_reason": null},
        "geography": {"value": "...", "human_review_needed": false, "human_review_reason": null},
        "time_period": {"value": "...", "human_review_needed": false, "human_review_reason": null},
        "frequency": {"value": null, "human_review_needed": false, "human_review_reason": null},
        "unit": {"value": "...", "human_review_needed": false, "human_review_reason": null}
      },
      "columns": [
        {
          "name": "...", "role": "identifier | dimension | measure | attribute | unknown",
          "concept": "...", "description": "...",
          "data_type": "string | integer | decimal | date | boolean | categorical | unknown",
          "unit": "...", "category": "...", "human_review_needed": false, "human_review_reason": null
        }
      ],
      "rows": [["...", "..."]],
      "notes": ["..."],
      "uncertain_cells": ["row 3, col 'Total': pymupdf_lines_strict=120 vs pymupdf_text=170, kept lines_strict"]
    }
  ]
}
Do not include a top-level "human_review_needed" on the table object -- that final flag is computed
deterministically from the field/column flags and uncertain_cells afterward, not by you."""


CLASSIFICATION_FIELDS = ("domain", "subject", "entity", "table_type", "geography", "time_period", "frequency", "unit")

# Standardized human_review_reason values, in table-level tie-break priority
# order (most specific/actionable first). Field- and column-level reasons are
# never coerced to this priority -- each keeps its own reason; this ordering
# is only used to pick ONE reason for the table-level rollup when several
# different reasons are present underneath it.
REVIEW_REASONS = (
    "garbled_extracted_value",
    "conflicting_extraction",
    "uncertain_extraction",
    "uncertain_semantic_role",
    "uncertain_concept",
    "ambiguous_column",
)
_REASON_PRIORITY = {reason: i for i, reason in enumerate(REVIEW_REASONS)}

# Private-use-area glyphs (icon fonts with no real Unicode mapping -- e.g. the
# trend-arrow symbols seen in this PDF's SDG tables) and common mojibake
# sequences from a text/encoding mismatch. Matches the kind of corruption
# described in the "garbled_extracted_value" case, not just any odd character.
_GARBLED_RE = re.compile("[\ue000-\uf8ff\ufffd]|[\u00c0-\u00ff][\u0080-\u00bf]")


def _looks_garbled(value: Any) -> bool:
    return isinstance(value, str) and bool(_GARBLED_RE.search(value))


def _rows_look_garbled(rows: List[List[Any]]) -> bool:
    return any(_looks_garbled(cell) for row in rows for cell in row)


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


def _normalize_field(field: Any) -> Dict[str, Any]:
    """Normalizes one classification field to {"value", "human_review_needed",
    "human_review_reason"}. Tolerates the model returning a bare scalar
    instead of the object shape (treated as the value, no review flag) or
    omitting the field entirely (defaults null/false/null)."""
    if isinstance(field, dict):
        needed, reason = _normalize_review_flag(field.get("human_review_needed", False), field.get("human_review_reason"))
        return {"value": field.get("value"), "human_review_needed": needed, "human_review_reason": reason}
    # Bare scalar (string/null) instead of the object shape -- keep the value.
    return {"value": field, "human_review_needed": False, "human_review_reason": None}


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
            columns.append({"name": c, "role": "unknown", "concept": None, "description": None,
                             "data_type": "unknown", "unit": None, "category": None,
                             "human_review_needed": False, "human_review_reason": None})
        elif isinstance(c, dict):
            needed, reason = _normalize_review_flag(c.get("human_review_needed", False), c.get("human_review_reason"))
            columns.append({
                "name": c.get("name", ""),
                "role": c.get("role") or "unknown",
                "concept": c.get("concept"),
                "description": c.get("description"),
                "data_type": c.get("data_type") or "unknown",
                "unit": c.get("unit"),
                "category": c.get("category"),
                "human_review_needed": needed,
                "human_review_reason": reason,
            })

    return {
        "title": table.get("title"),
        "description": table.get("description"),
        "classification": {field: _normalize_field(cls.get(field)) for field in CLASSIFICATION_FIELDS},
        "columns": columns,
        "rows": table.get("rows") or [],
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
        row value that looks corrupted/mojibake (garbled_extracted_value)
      - semantic classification uncertainty -> a classification field or
        column marked human_review_needed=true (each keeping its own
        reason), or a column whose role genuinely couldn't be determined
        (role == "unknown" -> uncertain_semantic_role, material to
        understanding the table regardless of whether the model itself
        flagged it)

    When multiple reasons are present, REVIEW_REASONS' order picks ONE for
    the table-level rollup -- the underlying field/column reasons are left
    untouched, so the frontend can still show exactly which field or column
    needs attention and why.

    Tables that simply haven't been semantically classified yet (the
    deterministic high-confidence/no-LLM path) are NOT "needing review" --
    that status is tracked separately via semantic_status. Absence of
    optional metadata (frequency/unit/description unknown) does not, by
    itself, trigger review either -- see the prompt's human_review_needed
    rules for why the model is told not to flag those."""
    if table.get("semantic_status") != "classified":
        return False, None

    reasons_present: set = set()

    uncertain_cells = table.get("uncertain_cells") or []
    rows = table.get("rows") or []
    if uncertain_cells:
        if any(_looks_garbled(note) for note in uncertain_cells) or _rows_look_garbled(rows):
            reasons_present.add("garbled_extracted_value")
        elif any(" vs " in str(note) for note in uncertain_cells):
            # Matches this pipeline's own uncertain_cells note format (see
            # TASK_A_RECONSTRUCTION_RULES / uncertain_cells example) --
            # "row X, col Y: candidateA=... vs candidateB=...".
            reasons_present.add("conflicting_extraction")
        else:
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


def _stamp_llm_metadata(page_result: Dict[str, Any], page_num: int) -> Dict[str, Any]:
    """Adds the pipeline-level bookkeeping fields (which extraction path
    produced this, whether it's been semantically classified, whether a
    human needs to review it and why, which page) that we already know
    deterministically -- not something we trust the LLM to self-report."""
    tables = []
    for t in page_result.get("tables", []):
        normalized = _normalize_table(t)
        normalized["semantic_status"] = "classified"
        normalized["extraction"] = {"method": "pymupdf+llm", "confidence": "llm_validated"}
        normalized["page"] = page_num
        normalized["human_review_needed"], normalized["human_review_reason"] = derive_human_review_needed(normalized)
        tables.append(normalized)
    return {"tables": tables}


def build_validation_prompt(page_num: int, candidates: List[Dict[str, Any]], text: str) -> str:
    sections = [f"--- {t['method']}, table {i + 1} ---\n{df_to_text(t['df'])}" for i, t in enumerate(candidates)]

    return f"""You are processing page {page_num} of an Indian government survey PDF (SDA_INDIA). You have two jobs on
this page, in order, in this same response:

A. RECONSTRUCT each table on the page.
B. UNDERSTAND what each reconstructed table means (initial semantic classification only).

You are given one or more independent extractions of the same page's table(s) by two different detection
strategies (pymupdf_lines_strict, which only catches tables with ruled border lines, and pymupdf_text, which
infers columns from text alignment/whitespace), plus the raw page text for grounding. The strategies frequently
disagree: one may merge two columns, split a multi-line header across rows, drop a footnote, or misread a
numeric column.

Raw page text:
{text[:3000]}

Extracted candidates:
{chr(10).join(sections) if sections else '(no table candidates extracted on this page)'}

{TASK_A_RECONSTRUCTION_RULES}

{TASK_B_CLASSIFICATION_RULES}

Return ONLY valid JSON (no markdown fences) shaped as:
{TABLE_SCHEMA_EXAMPLE}
If there is genuinely no table on this page, return {{"tables": []}}."""


def validate_page(client: openai.OpenAI, page_num: int, candidates: List[Dict[str, Any]], text: str) -> Dict[str, Any]:
    prompt = build_validation_prompt(page_num, candidates, text)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=SINGLE_PAGE_MAX_TOKENS,
    )
    text_out = resp.choices[0].message.content
    try:
        return json.loads(text_out)
    except json.JSONDecodeError:
        cleaned = re.sub(r"```[a-z]*\n?", "", text_out).strip().rstrip("`")
        return json.loads(cleaned)


def validate_all_pages(pages_grouped: Dict[int, List[Dict[str, Any]]], page_text: Dict[int, str],
                        n_workers: int = OPENAI_WORKERS) -> Dict[int, Dict[str, Any]]:
    client = openai.OpenAI()
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


# ── Stage 4: batched OpenAI validation (for the "needs LLM" bucket) ─────

def build_batch_validation_prompt(pages: List[int], pages_grouped: Dict[int, List[Dict[str, Any]]],
                                   page_text: Dict[int, str]) -> str:
    page_sections = []
    for page_num in pages:
        candidates = pages_grouped.get(page_num, [])
        sections = [f"  --- {t['method']}, table {i + 1} ---\n{df_to_text(t['df'], max_rows=30)}" for i, t in enumerate(candidates)]
        text = page_text.get(page_num, "")[:RAW_TEXT_CHARS_PER_PAGE_BATCHED]
        page_sections.append(
            f"=== PAGE {page_num} ===\n"
            f"Raw page text:\n{text}\n\n"
            f"Extracted candidates:\n{chr(10).join(sections) if sections else '  (no table candidates extracted on this page)'}"
        )

    return f"""You are processing {len(pages)} pages of an Indian government survey PDF (SDA_INDIA). For each page you
have two jobs, in order, in this same response: A) reconstruct each table on that page, B) understand what each
reconstructed table means (initial semantic classification only).

For each page below, you are given one or more independent extractions of that page's table(s) by two different
detection strategies (pymupdf_lines_strict, which only catches tables with ruled border lines, and pymupdf_text,
which infers columns from text alignment/whitespace), plus the raw page text for grounding. The strategies
frequently disagree: one may merge two columns, split a multi-line header across rows, drop a footnote, misread a
numeric column, glue the header into the first data row, or -- for pages routed here specifically because they
looked ambiguous -- produce a nearly empty or garbled result that only the raw text can clarify.

{chr(10).join('----------------------------------------' + chr(10) + s for s in page_sections)}

{TASK_A_RECONSTRUCTION_RULES}
- If a page genuinely has no table, its entry should be {{"tables": []}}.

{TASK_B_CLASSIFICATION_RULES}

Return ONLY valid JSON (no markdown fences) with exactly one top-level key "pages", mapping each page number
(as a string) to its own {{"tables": [...]}} object shaped like this per table:
{TABLE_SCHEMA_EXAMPLE}
Include an entry for every one of these page numbers, even if empty: {pages}"""


def validate_batch(client: openai.OpenAI, pages: List[int], pages_grouped: Dict[int, List[Dict[str, Any]]],
                    page_text: Dict[int, str]) -> Dict[int, Dict[str, Any]]:
    prompt = build_batch_validation_prompt(pages, pages_grouped, page_text)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=min(16000, MAX_TOKENS_PER_PAGE * len(pages)),
    )
    text_out = resp.choices[0].message.content
    try:
        parsed = json.loads(text_out)
    except json.JSONDecodeError:
        cleaned = re.sub(r"```[a-z]*\n?", "", text_out).strip().rstrip("`")
        parsed = json.loads(cleaned)

    by_page = parsed.get("pages", {})
    return {p: _stamp_llm_metadata(by_page.get(str(p), {"tables": []}), p) for p in pages}


def validate_all_pages_batched(pages_grouped: Dict[int, List[Dict[str, Any]]], page_text: Dict[int, str],
                                batch_size: int = BATCH_SIZE, n_workers: int = OPENAI_WORKERS,
                                progress_cb: Optional[Callable[[int, int], None]] = None,
                                api_key: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    client = openai.OpenAI(api_key=api_key)
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
                        validated[page_num] = _stamp_llm_metadata(result_single, page_num)
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

    def progress(stage: str, percent: int, message: str) -> None:
        log(message)
        if on_progress:
            on_progress(stage, percent, message)

    progress("classify", 2, f"Scanning {pdf_path.name} for text-bearing pages")
    text_pages, page_text = classify_pages(pdf_path)
    progress("classify", 10, f"{len(text_pages)} text-bearing page(s) found")

    progress("extract", 10, f"Extracting tables from {len(text_pages)} page(s)")
    all_tables = extract_all_tables(
        pdf_path, text_pages,
        progress_cb=lambda done, total: progress("extract", 10 + int(35 * done / total), f"Extracted {done}/{total} page(s)"),
    )
    progress("extract", 45, f"{len(all_tables)} table candidate(s) found")

    pages_grouped = filter_candidate_pages(group_by_page(all_tables))
    high_results, llm_pages, reason_counts = split_by_confidence(pages_grouped)
    progress("classify_confidence", 55,
              f"{len(high_results)} page(s) auto-accepted, {len(llm_pages)} page(s) need AI validation")

    validated_by_page: Dict[int, Dict[str, Any]] = dict(high_results)
    if llm_pages:
        llm_results = validate_all_pages_batched(
            llm_pages, page_text, api_key=api_key,
            progress_cb=lambda done, total: progress("validate", 55 + int(45 * done / total), f"AI-validated {done}/{total} page(s)"),
        )
        validated_by_page.update(llm_results)

    progress("done", 100, f"Pipeline complete -- {len(validated_by_page)} page(s) with tables")
    return dict(sorted(validated_by_page.items()))


# ── Orchestration ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N text-bearing pages (for quick smoke tests). Default: all pages.")
    parser.add_argument("--pages", type=str, default=None, help="Only process text-bearing pages in this 1-based PDF page range, e.g. '80-140'. Takes precedence over --limit.")
    parser.add_argument("--skip-validation", action="store_true", help="Stop after table extraction, skip the OpenAI step.")
    args = parser.parse_args()

    assert PDF_PATH.exists(), f"PDF not found at {PDF_PATH.resolve()}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    t_start = time.time()

    log(f"Stage 1: classifying pages in {PDF_PATH.name}")
    t0 = time.time()
    text_pages, page_text = classify_pages(PDF_PATH)
    log(f"  {len(text_pages)} text-bearing page(s) found in {time.time() - t0:.1f}s")

    if args.pages:
        start, end = (int(x) for x in args.pages.split("-", 1))
        target_pages = [p for p in text_pages if start <= p <= end]
    elif args.limit is not None:
        target_pages = text_pages[: args.limit]
    else:
        target_pages = text_pages
    log(f"Running on {len(target_pages)} page(s)")

    log(f"Stage 2: extracting tables with pymupdf ({CPU_WORKERS} workers)")
    t0 = time.time()
    all_tables = extract_all_tables(PDF_PATH, target_pages)
    log(f"  {len(all_tables)} table candidate(s) found in {time.time() - t0:.1f}s")

    pages_grouped = group_by_page(all_tables)
    log(f"  {len(pages_grouped)} page(s) have at least one table candidate")

    pages_grouped = filter_candidate_pages(pages_grouped)
    log(f"  {len(pages_grouped)} page(s) kept after requiring a lines_strict (ruled-border) hit -- drops likely false positives from the looser text strategy")

    log("Stage 3: confidence-classifying pages (no LLM)")
    t0 = time.time()
    high_results, llm_pages, reason_counts = split_by_confidence(pages_grouped)
    log(f"  {len(high_results)} page(s) auto-accepted (no LLM call), {len(llm_pages)} page(s) need OpenAI validation, in {time.time() - t0:.1f}s")
    for reason, count in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
        log(f"    [llm bucket] {count}x: {reason}")

    validated_by_page: Dict[int, Dict[str, Any]] = dict(high_results)

    if args.skip_validation:
        log(f"Skipping OpenAI validation (--skip-validation) -- output only has the {len(high_results)} auto-accepted page(s).")
    else:
        log(f"Stage 4: validating/restructuring {len(llm_pages)} page(s) with OpenAI (batches of {BATCH_SIZE}, {OPENAI_WORKERS} workers)")
        t0 = time.time()
        llm_results = validate_all_pages_batched(llm_pages, page_text)
        log(f"  validated {len(llm_results)} page(s) in {time.time() - t0:.1f}s")
        validated_by_page.update(llm_results)

        _log_representative_examples(llm_results, high_results)

    validated_by_page = dict(sorted(validated_by_page.items()))
    out_path = OUTPUT_DIR / f"validated_tables_pages_1-{max(target_pages)}.json"
    with open(out_path, "w") as f:
        json.dump(validated_by_page, f, indent=2, default=str)
    log(f"Saved {len(validated_by_page)} page(s) to {out_path}")
    log(f"Total time: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
