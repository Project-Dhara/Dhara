"""SDG metadata generation and parsing via LLM."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from app.services.metadata.excel_facts import (
    prepare_kyds_for_llm,
)

from app.services.metadata.nmds_llm import (
    _repair_json_text,
)

SDG_METADATA_FIELDS = [
    "Goal",
    "Target",
    "Indicator",
    "Series",
    "Metadata update",
    "Related indicators",
    "International organisations(s) responsible for global monitoring",
]

SDG_FIELD_CODES = {
    "Goal": "SDG_GOAL",
    "Target": "SDG_TARGET",
    "Indicator": "SDG_INDICATOR",
    "Series": "SDG_SERIES_DESCR",
    "Metadata update": "META_LAST_UPDATE",
    "Related indicators": "SDG_RELATED_INDICATORS",
    "International organisations(s) responsible for global monitoring": "SDG_CUSTODIAN_AGENCIES",
}

def generate_sdg_metadata_with_llm(
    excel_facts: Dict[str, Any],
    *,
    kyds: Dict[str, Any],
    complete_fn: Callable[[str, int], str],
) -> str:
    """Populate SDG indicator metadata fields from table/Excel facts + KYDS."""
    field_lines = "\n".join(
        f'* "{name}" ({SDG_FIELD_CODES[name]})' for name in SDG_METADATA_FIELDS
    )
    system_prompt = f"""You are a metadata-generation assistant for UN Sustainable Development Goals (SDG) indicator metadata.

Generate the following SDG indicator information fields using the provided `excel_facts` and `dataset_context` (KYDS):

{field_lines}

Rules:

* Use Excel / source-table facts as the primary source for what the data measures.
* Use KYDS context for purpose, department, frequency, and notes.
* Map the dataset to the most relevant SDG Goal, Target, and Indicator when evidence supports it.
* Write values in the UN SDG metadata style (e.g. "Goal 3: …", "Target 3.b: …", "Indicator 3.b.2: …").
* "Series" may list one or more series codes/descriptions, one per line when multiple apply.
* "Metadata update" should be an ISO date (YYYY-MM-DD) only when supported; otherwise null.
* "Related indicators" and custodian organisation(s) only when supported by the inputs; otherwise null.
* Do not invent unrelated SDG goals. If the SDG mapping cannot be determined, return null for Goal/Target/Indicator.
* Prefer explicit evidence over guesswork.

Return ONLY a single valid JSON object whose keys are exactly the field names listed above (human labels, not the codes).
Do not wrap it in markdown fences. Do not add commentary before or after the JSON.
Use double quotes for all keys and string values. Use null (not None) for unknown fields.
Escape any double quotes that appear inside string values.
"""
    kyds_llm = prepare_kyds_for_llm(kyds)
    user_content = {"excel_facts": excel_facts, "dataset_context": kyds_llm}
    prompt = f"{system_prompt}\n\n{json.dumps(user_content, default=str)}"
    return complete_fn(prompt, 3000)

def parse_llm_sdg_metadata_output(llm_output: str) -> Dict[str, Any]:
    """Parse LLM JSON into exactly SDG_METADATA_FIELDS (missing → None)."""
    raw = (llm_output or "").strip()
    if not raw:
        raise ValueError("LLM returned an empty SDG metadata response")

    candidates = [raw, _repair_json_text(raw)]
    last_err: Optional[Exception] = None
    parsed_obj: Optional[Dict[str, Any]] = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                parsed_obj = parsed
                break
        except json.JSONDecodeError as e:
            last_err = e

    if parsed_obj is None:
        repaired = _repair_json_text(raw)
        start, end = repaired.find("{"), repaired.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(re.sub(r",\s*([}\]])", r"\1", repaired[start : end + 1]))
                if isinstance(parsed, dict):
                    parsed_obj = parsed
            except json.JSONDecodeError as e:
                last_err = e

    if parsed_obj is None:
        detail = str(last_err) if last_err else "invalid JSON"
        raise ValueError(f"Could not parse SDG metadata JSON from LLM ({detail})")

    # Accept either human labels or UN codes as keys.
    code_to_label = {code.lower(): label for label, code in SDG_FIELD_CODES.items()}
    label_lower = {label.lower(): label for label in SDG_METADATA_FIELDS}
    out: Dict[str, Any] = {field: None for field in SDG_METADATA_FIELDS}
    for key, value in parsed_obj.items():
        k = str(key or "").strip()
        label = label_lower.get(k.lower()) or code_to_label.get(k.lower())
        if label:
            out[label] = value
    return out

__all__ = [
    "SDG_FIELD_CODES",
    "SDG_METADATA_FIELDS",
    "generate_sdg_metadata_with_llm",
    "parse_llm_sdg_metadata_output",
]
