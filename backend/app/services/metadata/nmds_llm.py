"""NMDS metadata generation and parsing via LLM."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from app.services.metadata.excel_facts import (
    prepare_kyds_for_llm,
)

def generate_metadata_with_llm(
    excel_facts: Dict[str, Any],
    *,
    kyds: Dict[str, Any],
    complete_fn: Callable[[str, int], str],
) -> str:
    """
    Populate catalogue metadata fields using both the programmatically-derived
    Excel facts and the human-provided KYDS form responses (kyds_responses).

    `complete_fn(prompt, max_tokens)` performs the actual LLM call -- pass
    `TableExtractor(api_key=..., provider=...)._complete`, built from the
    caller's own Settings key, so this routes through whichever provider the
    user configured instead of a fixed OpenAI env-var key.

    Only a trimmed subset of KYDS relevant to metadata generation is sent to the
    LLM (see prepare_kyds_for_llm), to save tokens. The full KYDS object should
    still be persisted as-is elsewhere (e.g. Postgres).
    """
    system_prompt = """You are a metadata-generation assistant for a data catalogue.

Generate the following metadata fields using the provided `excel_facts` and `dataset_context` (KYDS):

`title`, `product`, `category`, `geography`, `frequency`, `time_period`, `data_source`, `description`, `last_updated`, `future_release`, `key_statistics`, `remarks`.

Rules:

* Use Excel / source-table facts as the primary source for information about the actual data.
* Use KYDS context to understand the dataset's purpose, collection method, granularity, frequency, format, and notes.
* Do not invent or guess information. If a value cannot be determined, return `null`.
* Prefer explicit evidence in the facts over inference.
* Do not contradict explicit KYDS information.
* Generate concise, catalogue-ready values.
* `key_statistics` MUST be a short plain-text summary for catalogue display
  (2–6 bullets or short sentences). Highlight a few headline figures only
  (e.g. top categories, weights, notable highs/lows, or period-end values).
  Do NOT return JSON, do NOT return an array/object of table rows, and do NOT
  dump `sample_rows` or full month-by-month grids into this field.
* `last_updated` and `future_release` must be `null` unless explicitly supported by the inputs.
* `product` should identify the dataset/product represented by the source, not the file format.
* For `data_source`, prefer KYDS `department` (`dataset_context.department`) — the holding department/ministry. Never use a workbook filename, sheet name, table id, path-like string, or other Excel file evidence for `data_source`. Different groups may have different agency Sources when supported by the inputs, but filename is never a valid Source.
* `remarks` should contain relevant caveats, limitations, or contextual notes supported by the inputs.
* When `excel_facts.source_kind` is `"tables"` (e.g. SQL extract), treat table titles, column names, and sample rows as the workbook evidence.

Return ONLY a single valid JSON object for the fields listed above.
Do not wrap it in markdown fences. Do not add commentary before or after the JSON.
Use double quotes for all keys and string values. Use null (not None) for unknown fields.
Escape any double quotes that appear inside string values.
"""  # TODO: prompt to be added

    kyds_llm = prepare_kyds_for_llm(kyds)
    user_content = {"excel_facts": excel_facts, "dataset_context": kyds_llm}

    prompt = f"{system_prompt}\n\n{json.dumps(user_content, default=str)}"
    # Catalogue metadata can be verbose; under-tokenizing truncates JSON mid-string.
    return complete_fn(prompt, 2500)

METADATA_FIELDS = [
    "title", "product", "category", "geography", "frequency", "time_period",
    "data_source", "description", "last_updated", "future_release",
    "key_statistics", "remarks",
]

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
    # Smart quotes → ASCII
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
    # Trailing commas before } or ]
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

    # Last resort: slice from first { to last } after repair.
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
    "METADATA_FIELDS",
    "generate_metadata_with_llm",
    "parse_llm_metadata_output",
]
