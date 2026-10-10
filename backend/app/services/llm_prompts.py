"""
Central configuration: pipeline workers, LLM API limits, and prompt templates.
"""

from __future__ import annotations

from pathlib import Path

# ── PyMuPDF extraction ───────────────────────────────────────────────────────
TEXT_MIN_CHARS = 20
CPU_WORKERS = 3  # capped for ~8GB RAM hosts (was min(cpu_count(), 8))

# ── LLM API (PDF validation + catalogue extractor) ───────────────────────────
OPENAI_MODEL = "gpt-4o-mini"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
OPENAI_WORKERS = 6
BATCH_SIZE = 5
MAX_TOKENS_PER_PAGE = 5000
SINGLE_PAGE_MAX_TOKENS = 7000
RAW_TEXT_CHARS_PER_PAGE_BATCHED = 1500
PDF_VALIDATION_RAW_TEXT_CHARS = 3000
LLM_VALIDATION_TEMPERATURE = 0
BATCH_VALIDATION_MAX_TOKENS_CAP = 16000

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
