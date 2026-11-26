"""NMDS metadata generation and parsing via LLM."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, Optional

from app.services.llm_client import DEFAULT_SELF_HOSTED_MODEL
from app.services.metadata.excel_facts import (
    prepare_kyds_for_llm,
    shrink_facts_for_compact_llm,
)

METADATA_FIELDS = [
    "title", "product", "category", "geography", "frequency", "time_period",
    "data_source", "description", "last_updated", "future_release",
    "key_statistics", "remarks",
]

METADATA_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        field: {"type": ["string", "null"]} for field in METADATA_FIELDS
    },
    "required": list(METADATA_FIELDS),
    "additionalProperties": False,
}

METADATA_RESPONSE_FORMAT: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "catalogue_metadata",
        "strict": True,
        "schema": METADATA_JSON_SCHEMA,
    },
}

COMPACT_INSTRUCTIONS = """You fill a data catalogue form using ONLY the data above.
If a value is not clearly supported by the data, use null. Never invent facts or numbers.

Return ONE JSON object with exactly these keys:
title, product, category, geography, frequency, time_period, data_source, description, last_updated, future_release, key_statistics, remarks

Rules (keep every value short):
- title: the table or group title, max 15 words.
- product: the name of the dataset or product. Not a file format.
- category: one or two words, e.g. "Population".
- geography: each place and area type once, e.g. "Urban, Rural, MCD". Never use words like Region, District or Area as a place.
- frequency: e.g. "Annual" or "Monthly". null if unknown.
- time_period: e.g. "2023-24". null if unknown.
- data_source: use dataset_context.department. Never a filename or sheet name.
- description: 1-2 sentences, max 50 words. Say what the table covers: topic, geography, period, main measures. No sample rows, no lists, no figures.
- key_statistics: 2-4 short plain sentences with headline figures from the data. Plain text, not JSON.
- last_updated: null unless stated in the data.
- future_release: null unless stated in the data.
- remarks: one short sentence about coverage or caveats.
- product and description must be filled whenever a table title exists.

Example (different data, for format only):
{"title": "Rainfall by district", "product": "District Rainfall Statistics", "category": "Climate", "geography": "Rural, Urban", "frequency": "Annual", "time_period": "2022", "data_source": "Department of Meteorology", "description": "Annual rainfall recorded in each district, split by rural and urban areas, for 2022.", "last_updated": null, "future_release": null, "key_statistics": "Highest rainfall: 1,240 mm. Lowest: 310 mm.", "remarks": "Figures follow the source tables."}

Return only the JSON object."""

_FULL_SYSTEM_PROMPT = """You are a metadata-generation assistant for a data catalogue.

Generate the following metadata fields using the provided `excel_facts` and `dataset_context` (KYDS):

`title`, `product`, `category`, `geography`, `frequency`, `time_period`, `data_source`, `description`, `last_updated`, `future_release`, `key_statistics`, `remarks`.

Rules:

* Use Excel / source-table facts as the primary source for information about the actual data.
* Use KYDS context to understand the dataset's purpose, collection method, granularity, frequency, format, and notes.
* Prefer explicit evidence in the facts over inference. Do not contradict explicit KYDS information.
* Generate concise, catalogue-ready values. Stewards must not be left with blank core fields.
* REQUIRED whenever table/Excel facts or KYDS give any usable signal (do NOT return null for these):
  - `product` — the dataset/product the source represents (not a file format). Use title /
    KYDS dataset_name / sheet context when needed.
  - `description` — the catalogue AI summary. Write 1–2 short sentences (about 40–70 words,
    never more than ~80 words). State what the release covers using ONLY:
    group/table titles, product/category, geography, frequency, time period, and the main
    measures implied by column names. Be crisp and precise — no filler, no marketing tone.
    FORBIDDEN in `description`: sample cell values, row dumps, JSON/markdown tables,
    bullet lists, key:value grids, OCR noise, filenames, or inventing figures not in the
    metadata fields. Put figures in `key_statistics` instead. Never leave blank when a
    table title or columns exist.
  - `key_statistics` — short plain-text summary for catalogue display (2–6 bullets or short
    sentences). Highlight a few headline figures from sample_rows / periods only.
    Do NOT return JSON, do NOT return an array/object of table rows, and do NOT dump
    full month-by-month grids into this field.
  - `remarks` — caveats, coverage notes, or KYDS notes. If nothing specific is available,
    write one short neutral note (e.g. definitions and coverage follow the source tables).
* Other fields (`category`, `geography`, `frequency`, `time_period`) should be filled when
  evidence supports them; otherwise null is allowed.
* `geography` is the geographic coverage of the table, written once:
  - Name each distinct place (Delhi Cantt, MCD, NDMC) and area type (Urban, Rural) a single time.
  - Use normal case for words (Urban, not both URBAN and Urban). Keep short agency acronyms (MCD, NDMC).
  - Do not repeat a column header or level label as a place (Region, Geography, District, State, Area, Zone).
  - If a cell lists several places separated by commas, treat that as one set of places.
    Do not emit that same set again in another order.
  - Do not paste every raw cell. A short coverage line is enough, e.g. "Urban, Rural, Delhi Cantt, MCD, NDMC".
* `last_updated` and `future_release` must be `null` unless explicitly supported by the inputs.
* For `data_source`, prefer KYDS `department` (`dataset_context.department`) — the holding
  department/ministry. Never use a workbook filename, sheet name, table id, path-like string,
  or other Excel file evidence for `data_source`. Different groups may have different agency
  Sources when supported by the inputs, but filename is never a valid Source.
* When `excel_facts.source_kind` is `"tables"` (e.g. SQL / PDF extract), treat table titles,
  column names, and sample rows as the workbook evidence.

Return ONLY a single valid JSON object for the fields listed above.
Do not wrap it in markdown fences. Do not add commentary before or after the JSON.
Use double quotes for all keys and string values. Use null (not None) for unknown fields.
Escape any double quotes that appear inside string values.
"""

# Tiny local tags that need the compact prompt (beyond exact gemma3:1b).
_SMALL_MODEL_MARKERS = (
    ":1b",
    "1b-",
    "1b_",
    "gemma3:1b",
    "llama3.2:1b",
    "tinyllama",
    "qwen2.5:0.5b",
    "qwen2.5:1.5b",
)


def metadata_compact_override() -> Optional[bool]:
    """DHARA_METADATA_COMPACT: 1/true force on, 0/false force off, unset → None."""
    raw = (os.environ.get("DHARA_METADATA_COMPACT") or "").strip().lower()
    if not raw:
        return None
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def is_small_self_hosted_model(model: Optional[str]) -> bool:
    mid = (model or DEFAULT_SELF_HOSTED_MODEL or "").strip().lower()
    if not mid:
        return True
    if mid == DEFAULT_SELF_HOSTED_MODEL.lower():
        # Default desktop model is the 1B-class gemma.
        if any(m in mid for m in (":1b", "1b")):
            return True
    return any(marker in mid for marker in _SMALL_MODEL_MARKERS)


def use_compact_metadata_prompt(
    *,
    self_hosted: bool,
    model: Optional[str] = None,
) -> bool:
    override = metadata_compact_override()
    if override is not None:
        return override
    if not self_hosted:
        return False
    return is_small_self_hosted_model(model)


def generate_metadata_with_llm(
    excel_facts: Dict[str, Any],
    *,
    kyds: Dict[str, Any],
    complete_fn: Callable[..., str],
    compact: bool = False,
    deadline_monotonic: Optional[float] = None,
) -> str:
    """
    Populate catalogue metadata fields using Excel/table facts and KYDS.

    `complete_fn(prompt, max_tokens, **kwargs)` performs the LLM call — pass
    ``TableExtractor(...)._complete``. When ``compact`` is True, send a shrunk
    payload and short instructions suited to small local models.
    """
    kyds_llm = prepare_kyds_for_llm(kyds)
    if compact:
        facts = shrink_facts_for_compact_llm(excel_facts)
        data_blob = json.dumps(
            {"excel_facts": facts, "dataset_context": kyds_llm},
            default=str,
        )
        # Data first, instructions last (better for tiny models).
        prompt = f"{data_blob}\n\n{COMPACT_INSTRUCTIONS}"
        return complete_fn(
            prompt,
            700,
            response_format=METADATA_RESPONSE_FORMAT,
            temperature=0.1,
            deadline_monotonic=deadline_monotonic,
        )

    user_content = {"excel_facts": excel_facts, "dataset_context": kyds_llm}
    prompt = f"{_FULL_SYSTEM_PROMPT}\n\n{json.dumps(user_content, default=str)}"
    return complete_fn(
        prompt,
        2500,
        response_format=METADATA_RESPONSE_FORMAT,
        temperature=None,
        deadline_monotonic=deadline_monotonic,
    )


def _extract_json_object(text: str) -> str:
    """Pull the first top-level `{...}` object out of an LLM reply."""
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise json.JSONDecodeError("Unbalanced JSON object", text, start)


def _repair_json_text(text: str) -> str:
    """Best-effort cleanup for common LLM JSON mistakes."""
    cleaned = re.sub(r"```[a-zA-Z]*\n?", "", text or "").strip().rstrip("`").strip()
    cleaned = (
        cleaned.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )
    try:
        cleaned = _extract_json_object(cleaned)
    except json.JSONDecodeError:
        pass
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def parse_llm_metadata_output(llm_output: str) -> Dict[str, Any]:
    """
    Parse the JSON metadata object returned by generate_metadata_with_llm and
    normalize it to exactly METADATA_FIELDS (missing fields become None).
    Tolerates markdown fences, leading prose, trailing commas, and smart quotes.
    """
    raw = (llm_output or "").strip()
    if not raw:
        raise ValueError("LLM returned an empty metadata response")

    candidates = [raw, _repair_json_text(raw)]
    last_err: Optional[Exception] = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return {field: parsed.get(field) for field in METADATA_FIELDS}
        except json.JSONDecodeError as e:
            last_err = e
            continue

    repaired = _repair_json_text(raw)
    start, end = repaired.find("{"), repaired.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(re.sub(r",\s*([}\]])", r"\1", repaired[start : end + 1]))
            if isinstance(parsed, dict):
                return {field: parsed.get(field) for field in METADATA_FIELDS}
        except json.JSONDecodeError as e:
            last_err = e

    detail = str(last_err) if last_err else "invalid JSON"
    raise ValueError(f"Could not parse metadata JSON from LLM ({detail})")


__all__ = [
    "COMPACT_INSTRUCTIONS",
    "METADATA_FIELDS",
    "METADATA_JSON_SCHEMA",
    "METADATA_RESPONSE_FORMAT",
    "generate_metadata_with_llm",
    "is_small_self_hosted_model",
    "metadata_compact_override",
    "parse_llm_metadata_output",
    "use_compact_metadata_prompt",
]
