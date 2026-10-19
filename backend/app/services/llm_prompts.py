"""
Central configuration: pipeline workers, LLM API limits, and prompt templates.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# ── Host sizing (override via env on constrained or large boxes) ─────────────
_HOST_CPUS = max(1, os.cpu_count() or 1)

# ~1GB RSS headroom per PyMuPDF worker (PDF reopen + page DataFrames).
_MB_PER_CPU_WORKER = 1024
# Keep headroom for uvicorn / OS / LLM client so extract does not OOM the box.
# 1GB (not 1.5GB) so an 8GB laptop can still run ~3 workers — the historical
# local default — without OOM retries on typical extract loads.
_RAM_RESERVE_MB = 1024
# Fraction of total RAM treated as reclaimable (file cache / inactive pages).
# macOS vm_stat "free" understates this; 0.55 matches the macOS fallback ratio.
_RAM_RECLAIM_FRACTION = 0.55
# Sanity ceiling when autoscaling on very large instances (override via env).
_DEFAULT_CPU_WORKERS_MAX = 32


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _read_cgroup_memory_limit_mb() -> Optional[int]:
    """Docker/K8s memory limit when present; None if unlimited/unknown."""
    candidates = (
        "/sys/fs/cgroup/memory.max",  # cgroup v2
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",  # cgroup v1
    )
    for path in candidates:
        try:
            raw = Path(path).read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if not raw or raw == "max":
            continue
        try:
            nbytes = int(raw)
        except ValueError:
            continue
        # Huge sentinel values mean "no limit" on cgroup v1.
        if nbytes <= 0 or nbytes >= (1 << 60):
            continue
        return max(1, nbytes // (1024 * 1024))
    return None


def _read_cgroup_cpu_quota() -> Optional[int]:
    """Effective CPU count from cgroup quota when present; None if unlimited/unknown.

    Docker/K8s often expose host ``os.cpu_count()`` while the container is
    capped (e.g. 2 vCPU). Prefer the quota so we do not oversubscribe.
    """
    # cgroup v2: "max 100000" or "150000 100000" (quota period)
    try:
        raw = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").strip()
        parts = raw.split()
        if parts and parts[0] != "max":
            quota = int(parts[0])
            period = int(parts[1]) if len(parts) > 1 else 100_000
            if quota > 0 and period > 0:
                # Round up partial CPUs so a 1.5 quota still gets 2 workers max.
                return max(1, (quota + period - 1) // period)
    except Exception:
        pass

    # cgroup v1
    try:
        quota = int(
            Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text(encoding="utf-8").strip()
        )
        period = int(
            Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text(encoding="utf-8").strip()
        )
        if quota > 0 and period > 0:
            return max(1, (quota + period - 1) // period)
    except Exception:
        pass
    return None


def _effective_cpu_count() -> int:
    """Host CPUs, capped by cgroup CPU quota when the container is limited."""
    host = max(1, os.cpu_count() or 1)
    quota = _read_cgroup_cpu_quota()
    if quota is None:
        return host
    return max(1, min(host, quota))


def _read_linux_meminfo_mb() -> tuple[Optional[int], Optional[int]]:
    """Return (MemAvailable_mb, MemTotal_mb) from /proc/meminfo."""
    avail: Optional[int] = None
    total: Optional[int] = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) // 1024
                elif line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
    except Exception:
        return None, None
    return avail, total


def _read_macos_mem_mb() -> tuple[Optional[int], Optional[int]]:
    """Return (approx_available_mb, total_mb) via sysctl / vm_stat."""
    import subprocess

    total: Optional[int] = None
    try:
        out = subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        total = max(1, int(out) // (1024 * 1024))
    except Exception:
        return None, None

    # Prefer free+inactive pages when vm_stat is available; else ~55% of total.
    avail: Optional[int] = None
    try:
        vm = subprocess.check_output(
            ["vm_stat"], stderr=subprocess.DEVNULL, text=True
        )
        page_size = 4096
        for line in vm.splitlines():
            if "page size of" in line:
                # e.g. "Mach Virtual Memory Statistics: (page size of 16384 bytes)"
                parts = line.replace("(", " ").replace(")", " ").split()
                for i, tok in enumerate(parts):
                    if tok.isdigit() and i + 1 < len(parts) and parts[i + 1].startswith("bytes"):
                        page_size = int(tok)
                        break
        counts = {"Pages free": 0, "Pages inactive": 0, "Pages speculative": 0}
        for line in vm.splitlines():
            for key in counts:
                if line.startswith(key):
                    num = line.split(":")[-1].strip().rstrip(".")
                    counts[key] = int(num.replace(".", ""))
                    break
        avail = max(
            1,
            ((counts["Pages free"] + counts["Pages inactive"] + counts["Pages speculative"])
             * page_size)
            // (1024 * 1024),
        )
    except Exception:
        avail = max(1, int(total * _RAM_RECLAIM_FRACTION))
    return avail, total


def _available_ram_mb() -> Optional[int]:
    """Best-effort usable RAM for extract workers (cgroup / Linux / macOS)."""
    cgroup = _read_cgroup_memory_limit_mb()
    avail, total = _read_linux_meminfo_mb()
    if avail is None and total is None:
        avail, total = _read_macos_mem_mb()

    # Inside Docker the cgroup limit is the real ceiling even if host MemAvailable
    # looks larger.
    if cgroup is not None:
        if total is None:
            total = cgroup
        else:
            total = min(total, cgroup)
        if avail is None:
            avail = total
        else:
            avail = min(avail, cgroup)

    if avail is None and total is None:
        return None

    # File-cache / inactive pages are reclaimable. macOS vm_stat "free" often
    # understates this and would collapse workers to 1 on an 8GB laptop.
    if total is not None:
        reclaim_floor = max(1, int(total * _RAM_RECLAIM_FRACTION))
        if avail is None:
            avail = reclaim_floor
        else:
            avail = max(avail, min(reclaim_floor, max(1, total - 512)))
    return max(1, int(avail))


def _default_cpu_workers() -> int:
    """Process-pool size for PyMuPDF — scales with instance CPUs and RAM.

    Each worker re-opens the full PDF and holds page DataFrames. On small hosts
    (e.g. 8GB laptops) we stay conservative so extract does not OOM and retry.
    On larger servers / containers, workers track effective CPUs (host count
    capped by cgroup quota) and available RAM (~1GB/worker after a 1GB
    reserve) up to ``PDF_CPU_WORKERS_MAX``. An 8GB laptop typically gets 3
    workers (the previous local default).
    """
    cpus = _effective_cpu_count()
    # Leave one core for the API process when the box has spare capacity.
    cpu_cap = cpus if cpus <= 2 else max(1, cpus - 1)

    avail = _available_ram_mb()
    hard_max = _env_int("PDF_CPU_WORKERS_MAX", _DEFAULT_CPU_WORKERS_MAX)
    if avail is None:
        # Unknown RAM: scale with CPUs but stay modest.
        return max(1, min(cpu_cap, 4, hard_max))

    usable = max(512, int(avail) - _RAM_RESERVE_MB)
    mem_cap = max(1, usable // _MB_PER_CPU_WORKER)
    return max(1, min(cpu_cap, mem_cap, hard_max))


def resolve_cpu_workers() -> int:
    """Effective PyMuPDF worker count (env override or autoscaled default)."""
    raw = (os.environ.get("PDF_CPU_WORKERS") or "").strip()
    if raw:
        return _env_int("PDF_CPU_WORKERS", 1)
    return _default_cpu_workers()


# ── PyMuPDF extraction ───────────────────────────────────────────────────────
TEXT_MIN_CHARS = 20
# Resolved at import for callers/logging; extract path re-resolves at run time
# so server instances pick up current cgroup/RAM without a code change.
CPU_WORKERS = resolve_cpu_workers()
# Pages per process-pool task. Smaller chunks → more frequent progress updates
# and less work lost when a worker is OOM-killed.
EXTRACT_CHUNK_PAGES = _env_int("PDF_EXTRACT_CHUNK_PAGES", 8)

# ── LLM API (PDF validation + catalogue extractor) ───────────────────────────
OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
# I/O-bound OpenAI calls — concurrency is not CPU-bound. Default high enough
# that ~100+ uncertain pages finish in a few waves rather than a long queue.
# Raise via PDF_OPENAI_WORKERS if the provider allows; back off on 429s.
OPENAI_WORKERS = _env_int("PDF_OPENAI_WORKERS", 20)
BATCH_SIZE = _env_int("PDF_LLM_BATCH_SIZE", 6)
MAX_TOKENS_PER_PAGE = 4500
SINGLE_PAGE_MAX_TOKENS = 7000
RAW_TEXT_CHARS_PER_PAGE_BATCHED = 1200
PDF_VALIDATION_RAW_TEXT_CHARS = 2500
LLM_VALIDATION_TEMPERATURE = 0
BATCH_VALIDATION_MAX_TOKENS_CAP = 18000
# Rows of each candidate grid included in the LLM prompt (reconstruction still
# uses full candidate grids in post-stamp alignment — this only shrinks prompt).
LLM_PROMPT_MAX_ROWS = _env_int("PDF_LLM_PROMPT_MAX_ROWS", 25)

# ── CLI sample paths (``python -m app.services.extraction.pdf``) ─────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[2]
PDF_PATH = _BACKEND_DIR.parent / "SDA_INDIA_0.pdf"
OUTPUT_DIR = _BACKEND_DIR / "data" / "pdf_extraction"

# ── PDF LLM validation prompts (shared single-page + batched) ────────────────

TASK_A_RECONSTRUCTION_RULES = """TASK A -- RECONSTRUCT THE TABLE:
- Reconcile the candidate extractions into ONE clean, correct table per distinct table on the page.
- Count the DISTINCT physical tables from ruled-border candidates (pymupdf_lines_strict /
  pymupdf_lines) that have different vertical positions / captions. You MUST emit that many
  separate tables in "tables" (one object each). Do NOT merge two ruled candidates — or their
  rows — into a single output table unless the raw text makes clear they are literally one table
  split by a page/column break (same header, no new caption in between). When in doubt, keep
  them as separate tables; a pymupdf_text candidate that spans multiple captions is a
  whitespace-alignment artifact, not evidence that the underlying tables should be combined.
- NEVER invent a value that isn't present in at least one candidate or the raw text.
- Prefer whichever candidate got a given row/column right; you may combine cells from different
  candidates that describe the SAME physical table (same bbox / same caption), not across tables.
- If candidates disagree on a cell and you can't tell which is right from the raw text, keep the
  pymupdf_lines_strict (or pymupdf_lines) value and add a note in "uncertain_cells".
- Flatten multi-row / merged headers into ONE name per physical data column. Do NOT promote a
  spanning group label into its own extra column.
  Example — source header grid:
      Year | In Lakhs (spans 2 cols) | *Birth Rate
           | Mid Year Population | No. of Births |
    Correct columns (4): ["Year", "Mid Year Population as on 1st July (In Lakhs)",
    "No. of Births (In Lakhs)", "*Birth Rate"]
    WRONG (5 phantom columns): ["Year", "In Lakhs", "Birth Rate", "Mid Year Population", "No. of Births"]
  Every data row length MUST equal len(columns); values stay under their leaf headers.
- Column names in the output MUST be unique. If the same leaf header (e.g. a year, "Male"/"Female",
  or a repeated sub-metric) appears under two different parent groups, you MUST fold the parent group
  into the name so the two columns read differently (e.g. "2023-24 (Sanctioned)" and
  "2023-24 (Released)", or "Male (Institutional Births)" and "Male (Non-Institutional Births)").
  Never emit two columns with the identical name.
- SECTION / CATEGORY HEADER ROWS: a row that only has a value in the first 1-2 columns (e.g. a letter
  or index like "A"/"B" plus a group label like "Vital Rates (per 1000)") and is blank in every measure
  column is a section heading for the rows below it, not a data point to discard. Keep it as its own
  row with the group label in place and null in the other columns -- do NOT silently drop it (that loses
  the grouping context for every row underneath) and do NOT invent values to fill it in.
- BLANK-STUB / PERCENTAGE CONTINUATION ROWS: when a ruled table alternates a labelled row (e.g. Year
  "1991" with absolute counts) with a following row whose first cell is empty but other cells hold
  values — especially parenthetical shares like "(10.6)", "(13.6)", or "*(45.18)" — that second row is
  REAL DATA, not a footnote and not a "(1)(2)(3)" column-index strip. You MUST emit it as its own row
  with null/empty in the blank stub column and the parenthetical values preserved exactly (including
  parentheses and leading "*"). Never collapse it into the previous year row and never omit it.
- SEX-PAIR ROWS (M then F): cause-of-death and similar tables list each disease twice — Male then Female.
  The Female row often has empty S.No. / disease-name cells. Candidates may also arrive with M/F and age
  values already split into separate rows. You MUST keep one output row per sex line (never merge M and F
  into one cell, never stack "M F M F" or multiple age values inside a single cell). Preserve empty stub
  cells on the F row.
- AGE-BAND COLUMNS: when the PDF grid shows many age columns (<1, 1-4, …, Not stated) plus Total under an
  "Age in Years" group, emit EVERY leaf as its own column (typically ~11 age bands + Total). Do NOT collapse
  them into one "Age" column or pack multiple numbers into the last cell.
- IDENTITY STUB COLUMNS: keep S.No. / serial and Name of the Disease (or equivalent label columns) as their
  own columns to the left of Sex. Never drop them and start the table at Sex — that loses the disease
  hierarchy and makes every measure row ambiguous. Also keep section banner rows (e.g. "I CERTAIN INFECTIOUS
  AND PARASITIC DISEASES …") that have labels in the stub columns and blank measures.
- For "title", use the descriptive caption visible in the table or page text
  (e.g. "LIVE BIRTHS BY BIRTH ORDER AND BIRTH WEIGHT (URBAN)"). Do NOT use a short
  table identifier alone as the title (e.g. "TABLE: B-22", "Table B-6", "Statement 4.1").
  If both a short id row and a descriptive caption appear, put the id in "notes" as
  "table_id: …" and the descriptive text in "title". Preserve a description if visible.
- SYMBOLIC / ICON CELLS (especially Direction / Trend / Change columns):
  PDF extractors often emit private-use or icon-font glyphs for green/red trend arrows instead of real text.
  ONLY when a Direction / Trend / Change column is already present in the candidates or clearly visible
  as a table header in the raw text:
    * Interpret upward / green / "increase" arrows as the cell value "up"
    * Interpret downward / red / "decrease" arrows as the cell value "down"
    * Write "up" or "down" in the reconstructed "rows" (never leave the raw arrow glyph / tofu / �).
    * Every row MUST include that Direction/Trend cell — the rows array length must equal the columns
      array length. Do not declare a Direction column and then omit that cell from the row.
    * If you cannot tell whether an arrow is up or down, still put your best guess ("up" or "down") in the
      cell, add a note in "uncertain_cells", and flag the column for human review (see Task B input_type).
  Do NOT invent, append, or fill a Direction / Trend / Change column when none exists in the source
  table. If the table has no such column, omit it entirely (do not invent up/down values)."""

TASK_B_CLASSIFICATION_RULES = """TASK B -- UNDERSTAND THE TABLE (initial semantic classification only):
After reconstructing a table, determine what it appears to mean, using the page text, table title, headers,
extracted values, and any notes/footnotes as context.

At table level, identify where possible: domain, subject, entity, table_type, geography, time_period,
frequency, unit. Each of these is an object:
  {"value": ..., "human_review_needed": true|false, "input_type": "dropdown"|"inputbox"|null,
   "input_options": [...]|null, "human_review_reason": "..."|null}
-- see the human_review_needed / input_type rules below.

At column level, for each column identify:
- "role": one of "identifier", "dimension", "measure", "attribute", "unknown"
- "concept": the semantic concept the column represents (e.g. "State", "Population", "Primary Health Centre")
- "description": a short description of the column
- "data_type": one of "string", "integer", "decimal", "date", "boolean", "categorical", "unknown"
- "unit": the unit of measurement if applicable, else null
- "category": a sub-category/grouping value if applicable (e.g. a "Male" column's category is "Male"), else null
- "human_review_needed": true|false
- "input_type": "dropdown" | "inputbox" | null  -- UI hint for how a human should correct this field/column
- "input_options": array of allowed strings when input_type is "dropdown", else null
- "human_review_reason": "..."|null -- see the rules below

Examples:
- "State" -> role: dimension, concept: State, data_type: categorical,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null
- "PHC ID" -> role: identifier, concept: Primary Health Centre, data_type: string,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null
- "Male" -> role: measure, concept: Population, category: Male, data_type: integer,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null
- "Total" -> role: measure, concept: Population, data_type: integer,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null
- "PHC" (ambiguous abbreviation, could mean several things) -> concept: Primary Health Centre (best guess),
  human_review_needed: true, input_type: "inputbox", input_options: null,
  human_review_reason: "uncertain_concept"
- "Direction" / "Trend" (ONLY if that column is already in the source table; values shown as up/down
  arrows in the PDF) -> role: attribute, concept: Direction,
  data_type: categorical, rows use "up"|"down",
  human_review_needed: true, input_type: "dropdown", input_options: ["up", "down"],
  human_review_reason: "garbled_extracted_value"
  (or "uncertain_extraction" if the arrow was ambiguous). Even when every arrow was confidently mapped,
  still set human_review_needed: true and input_type: "dropdown" for Direction-like columns so a human
  can confirm via dropdown rather than free-text. Never add this column when it is absent from the table.

human_review_needed / input_type / human_review_reason rules (both for each classification field above, and for each column):
- Give your best semantic interpretation always -- never leave a field empty just because you're unsure;
  put your best guess in "value"/the column fields, and use human_review_needed to flag the uncertainty
  instead of refusing to answer.
- Set human_review_needed=true ONLY when there is MEANINGFUL uncertainty or ambiguity a human should
  resolve -- e.g. a column name/abbreviation that could plausibly mean more than one thing, a table title
  that doesn't clearly indicate its subject, a role you genuinely can't determine (role: "unknown"), OR a
  Direction/Trend-like column whose values came from icon/arrow glyphs (always reviewable via dropdown).
- When human_review_needed=true you MUST also set input_type:
    * "dropdown" -- the correct value is one of a small fixed set (Direction/Trend -> ["up","down"];
      yes/no; similar binary/ternary categorical choices). Always include "input_options" as that list.
    * "inputbox" -- the human should type free text (ambiguous labels, garbled names, open concepts).
      Set "input_options" to null.
- When human_review_needed=false, set input_type: null and input_options: null.
- Do NOT set human_review_needed=true just because an OPTIONAL field is simply not present in the source
  (e.g. frequency or unit legitimately don't apply to this table) -- in that case use value: null,
  human_review_needed: false, input_type: null, input_options: null, human_review_reason: null.
  Missing-and-not-applicable is not the same as uncertain-and-ambiguous.
- When human_review_needed=true, human_review_reason MUST be exactly one of these standardized values
  (do not invent your own wording):
    "uncertain_extraction"    -- the extracted value itself may be wrong, incomplete, or hard to read
    "conflicting_extraction"  -- two extraction candidates disagree and you had to pick one
    "garbled_extracted_value" -- the extracted text contains corrupted/mojibake/encoding-broken characters
                                  OR icon-font arrow glyphs that were interpreted as up/down
    "uncertain_semantic_role" -- you cannot confidently tell what role this column/field plays
    "uncertain_concept"       -- the name/abbreviation could plausibly mean more than one real-world concept
    "ambiguous_column"        -- some other column-level ambiguity not covered by the above
- When human_review_needed=false, human_review_reason MUST be null.
- Also add a brief note in "notes" explaining the uncertainty (e.g. "column 'PHC' -- could be Primary Health
  Centre or another facility type, please confirm"; or "Direction column used arrow icons; mapped to up/down").
- Do NOT hallucinate standards, codes, entities, units, or dates that aren't supported by the page.
- Do NOT attempt harmonization, do NOT map to any external standard/code list (e.g. NMDS/LGD/NCO), and do NOT
  group this table with any other table. That happens in a later stage, not here."""

TABLE_SCHEMA_EXAMPLE = """{
  "tables": [
    {
      "title": "...",
      "description": "...",
      "classification": {
        "domain": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "subject": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "entity": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "table_type": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "geography": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "time_period": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "frequency": {"value": null, "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null},
        "unit": {"value": "...", "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null}
      },
      "columns": [
        {
          "name": "...", "role": "identifier | dimension | measure | attribute | unknown",
          "concept": "...", "description": "...",
          "data_type": "string | integer | decimal | date | boolean | categorical | unknown",
          "unit": "...", "category": "...",
          "human_review_needed": false, "input_type": null, "input_options": null, "human_review_reason": null
        }
      ],
      "rows": [["...", "..."], ["...", "..."]],
      "notes": [],
      "uncertain_cells": ["row 3, col 'Total': pymupdf_lines_strict=120 vs pymupdf_text=170, kept lines_strict"]
    }
  ]
}
Do not include a top-level "human_review_needed" on the table object -- that final flag is computed
deterministically from the field/column flags and uncertain_cells afterward, not by you.
When human_review_needed is true, always pair it with input_type ("dropdown" or "inputbox") as shown above.
Do not include a Direction/Trend column in columns/rows unless it is present in the source table."""


def pdf_single_page_validation_user_prompt(
    *,
    page_num: int,
    raw_page_text: str,
    candidates_block: str,
    count_hint: str,
) -> str:
    """Full user message for one-page PDF table reconstruct + classify."""
    return f"""You are processing page {page_num} of a government statistical PDF. You have two jobs on
this page, in order, in this same response:

A. RECONSTRUCT each table on the page.
B. UNDERSTAND what each reconstructed table means (initial semantic classification only).

You are given one or more independent extractions of the same page's table(s) by detection
strategies (pymupdf_lines_strict / pymupdf_lines for ruled borders, and pymupdf_text for
whitespace alignment), plus the raw page text for grounding. The strategies frequently
disagree: one may merge two columns, split a multi-line header across rows, drop a footnote, or misread a
numeric column. Candidates with different vertical positions are DIFFERENT tables.

Raw page text:
{raw_page_text}

Extracted candidates:
{candidates_block}

{count_hint}{TASK_A_RECONSTRUCTION_RULES}

{TASK_B_CLASSIFICATION_RULES}

Return ONLY valid JSON (no markdown fences) shaped as:
{TABLE_SCHEMA_EXAMPLE}
If there is genuinely no table on this page, return {{"tables": []}}."""


def pdf_batch_validation_user_prompt(
    *,
    page_numbers: list[int],
    page_sections_block: str,
) -> str:
    """Full user message for batched PDF validation."""
    return f"""You are processing {len(page_numbers)} pages of a government statistical PDF. For each page you
have two jobs, in order, in this same response: A) reconstruct each table on that page, B) understand what each
reconstructed table means (initial semantic classification only).

For each page below, you are given one or more independent extractions of that page's table(s) by detection
strategies (pymupdf_lines_strict / pymupdf_lines for ruled borders, and pymupdf_text for whitespace alignment),
plus the raw page text for grounding. Candidates at different vertical positions are DIFFERENT tables — do not
merge them. The strategies frequently disagree: one may merge two columns, split a multi-line header across rows,
drop a footnote, misread a numeric column, glue the header into the first data row, or -- for pages routed here
specifically because they looked ambiguous -- produce a nearly empty or garbled result that only the raw text can clarify.

{page_sections_block}

{TASK_A_RECONSTRUCTION_RULES}
- If a page genuinely has no table, its entry should be {{"tables": []}}.

{TASK_B_CLASSIFICATION_RULES}

Return ONLY valid JSON (no markdown fences) with exactly one top-level key "pages", mapping each page number
(as a string) to its own {{"tables": [...]}} object shaped like this per table:
{TABLE_SCHEMA_EXAMPLE}
Include an entry for every one of these page numbers, even if empty: {page_numbers}"""


def excel_table_structure_prompt(
    *,
    title: str,
    description: str,
    n_cols: int,
    n_rows: int,
    n_sample: int,
    grid_text: str,
) -> str:
    desc_line = f"Description: {description}" if description else ""
    return f"""Analyze this government statistical table body and return its structure.

Table: {title}
{desc_line}
Columns: {n_cols}, Total rows: {n_rows}

First {n_sample} rows (tab-separated):
{grid_text}

Return JSON with:
- "header_rows": count of rows at start that are column headers (not data)
- "skip_rows": 0-based row indices to skip (e.g. column-number rows like "(1)(2)(3)")
- "columns": exactly {n_cols} flat column names

For multi-level headers (group row + sub-column row), combine: "AGE_<1", "AGE_1-4"
Return ONLY valid JSON, no markdown fences."""


def excel_category_metadata_prompt(
    *,
    title: str,
    description: str,
    header_block: str,
    n_columns: int,
    columns_preview: str,
    data_sample_block: str,
    notes_line: str,
) -> str:
    desc_line = f"Description: {description}" if description else ""
    return f"""You are analyzing a government statistical table to build a metadata catalogue.

Table: {title}
{desc_line}

Original multi-level column headers (before flattening):
{header_block}

Flat column names after AI extraction ({n_columns} total):
  {columns_preview}

First few data rows (first 6 values each):
{data_sample_block}
{notes_line}

Your task: identify EVERY categorical dimension in this table.
A "category" is any grouping variable — examples:
- Column-group headers like RURAL / URBAN (spans multiple sub-columns)
- Sub-group headers like INSTITUTION / DOMICILIARY
- Cross-tabulation variables like Male / Female, Age bands, Year
- Row-dimension labels like State, District, Block, Taluk

Rules:
- Each category name must be UNIQUE — do not repeat the same category twice
- Each value within a category must be UNIQUE — list each value only once
- Merge overlapping categories into one (e.g. "Area" and "Location Type" are the same)
- Omit "Total" or "Grand Total" rows — those are aggregates, not categories

For each category:
- Give it a clear human-readable name (e.g. "Area Type", "Care Setting", "Gender")
- Write a one-sentence description of what it classifies
- List every unique value you can identify from the headers and data sample
- Generate a short UPPERCASE_UNDERSCORE code for each value
- Write a brief plain-English description for each value

Return ONLY a valid JSON object — no prose, no markdown fences:
{{
  "categories": [
    {{
      "name": "Area Type",
      "description": "Classifies data by geographic area type",
      "values": [
        {{"value": "Rural", "code": "RURAL", "description": "Data from rural areas outside municipal limits"}},
        {{"value": "Urban", "code": "URBAN", "description": "Data from urban areas within municipal limits"}}
      ]
    }}
  ]
}}"""


def excel_catalogue_enrichment_prompt(
    *,
    table_id: str,
    sheet: str,
    columns: list,
    sample_rows_json: str,
    title: str,
) -> str:
    return f"""You are a data cataloguer for the Delhi Economic Survey (DES). Given an extracted Excel table, generate structured catalogue metadata.

Source Table ID: {table_id}
Sheet: {sheet}
Columns ({len(columns)}): {columns}
Sample rows (first 6): {sample_rows_json}
Existing title: {title}

Return ONLY a JSON object with exactly these fields:
{{
  "short_description": "1-2 sentence factual summary of what data this table contains",
  "long_description": "3-5 sentence detailed description: what is measured, geographic scope, time period, disaggregation levels, and how to interpret the data",
  "units": "measurement unit as a short string, e.g. 'Count', 'Percentage', 'Rs. Crore', 'Lakhs', 'Rate per 1000'",
  "classifications": {{
    "dimension_name": ["value1", "value2"]
  }},
  "age_column_keys": {{
    "col_name_or_key": "readable age label"
  }}
}}

Rules for classifications:
- Identify categorical dimensions from column names and sample data values (e.g. gender_classification, area_type, administrative_body, place_of_occurrence)
- For each dimension list up to 15 unique values found in column names or sample data
- Use snake_case dimension names
- Do NOT include numeric/quantitative columns as classifications
- If no clear categorical dimensions exist, return an empty object {{}}

Rules for age_column_keys:
- Only populate if the table has columns representing age groups (e.g. "<1", "1-4", "15-24", "65+")
- Map the column name to a readable human label
- Return empty object {{}} if no age-related columns exist

Return only valid JSON, no markdown fences, no explanation."""


# ── Preview: AI search over extracted table titles ──────────────────────────

TABLE_AI_SEARCH_PROMPT = """You help a data steward search a list of extracted tables by natural language.

The steward wrote this request:
{prompt}

Here is the catalog of tables still in the review (id, page, title, optional summary).
Use ONLY these ids.
{catalog_json}

Return ONLY valid JSON (no markdown):
{{
  "intent": "find",
  "table_ids": ["1-0", "2-1"],
  "rationale": "one short sentence explaining the selection"
}}

Intent rules:
- Use "find" for search, locate, identify, show, or filter requests.
- Use "remove" ONLY when the steward clearly asks to remove, delete, drop, or discard tables.
- When unsure between find and remove, choose "find".

Selection rules:
- Prefer precision over recall: only include tables that clearly match the request.
- If nothing matches, return "table_ids": [] and a brief rationale.
- Never invent ids. Every id must appear in the catalog.
- Match on title, page, summary, or obvious patterns (appendix, blank, chart, duplicate, topic).
"""
