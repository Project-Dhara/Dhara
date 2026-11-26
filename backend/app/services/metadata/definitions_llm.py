"""LLM-backed classification definition fill."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.metadata.nmds_llm import _repair_json_text, use_compact_metadata_prompt

# Cloud / larger models: one LLM completion cannot fit hundreds of short defs
# under a small token ceiling. Batch so each call stays within budget.
DEFINITION_BATCH_SIZE = 40
DEFINITION_BATCH_SIZE_COMPACT = 15
DEFINITION_MAX_TOKENS = 4096
DEFINITION_COLUMN_DEADLINE_SEC = 180.0


def _definition_response_format(values: List[str]) -> Dict[str, Any]:
    """Strict json_schema mapping each exact value string → definition string."""
    props = {str(v): {"type": "string"} for v in values}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "classification_definitions",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": props,
                "required": [str(v) for v in values],
                "additionalProperties": False,
            },
        },
    }


def _shrink_facts_for_compact(facts: Dict[str, Any], *, max_chars: int = 1500) -> Dict[str, Any]:
    raw = json.dumps(facts or {}, default=str)
    if len(raw) <= max_chars:
        return facts or {}
    # Prefer a truncated JSON string field the model can still read.
    return {"summary": raw[:max_chars]}


def _parse_definitions_json(text: str, values: List[str]) -> Dict[str, str]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("LLM returned an empty definitions response")

    candidates = [raw, _repair_json_text(raw)]
    parsed_obj: Optional[Dict[str, Any]] = None
    last_err: Optional[Exception] = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                parsed_obj = parsed
                break
        except json.JSONDecodeError as e:
            last_err = e
            continue

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
        raise ValueError(f"Could not parse definitions JSON from LLM ({detail})")

    out: Dict[str, str] = {}
    for v in values:
        d = parsed_obj.get(v)
        if d is None:
            d = next(
                (
                    parsed_obj[k]
                    for k in parsed_obj
                    if str(k).strip().lower() == str(v).strip().lower()
                ),
                None,
            )
        if d is None:
            continue
        if isinstance(d, dict):
            d = d.get("definition") or d.get("description") or d.get("title")
        if not d or isinstance(d, (list, dict)):
            continue
        words = str(d).strip().rstrip(".").split()
        if not words:
            continue
        out[str(v)] = " ".join(words[:8])
    return out


def _fill_classification_definitions_batch(
    complete_fn: Callable[..., str],
    column_name: str,
    values: List[str],
    facts: Dict[str, Any],
    *,
    compact: bool = False,
    deadline_monotonic: Optional[float] = None,
) -> Dict[str, str]:
    """Same prompt + parse rules for a single value batch."""
    if not values:
        return {}

    if compact:
        facts_payload = _shrink_facts_for_compact(facts)
        data_blob = json.dumps(
            {"column": column_name, "values": values, "facts": facts_payload},
            default=str,
        )
        prompt = (
            f"{data_blob}\n\n"
            "Return ONLY a JSON object mapping each value (exact string) to a short definition.\n"
            "Rules: definitions only (no codes); each definition ≤ 8 words; "
            "plain gloss if facts are thin; no statistics."
        )
        max_tokens = min(1200, 80 + 28 * len(values))
        temperature = 0.1
    else:
        prompt = f"""You write brief catalogue definitions for classification VALUES (labels from the data).

Dataset facts from the source workbook / catalogue record:
{json.dumps(facts or {{}}, default=str)[:4500]}

Column name: {column_name}
Values: {json.dumps(values)}

Return ONLY a JSON object mapping each value (exact string) to a short definition string.
Rules:
- Fill DEFINITIONS only — do not invent or return codes.
- Keep each definition under 8 words. Prefer meaning over repeating the label.
- No full sentences unless needed. No statistics. No occupation/NCO codes.
- If facts do not explain a label, give a short plain-language gloss."""
        max_tokens = min(DEFINITION_MAX_TOKENS, 160 + 40 * len(values))
        temperature = 0.1

    text = complete_fn(
        prompt,
        max_tokens,
        response_format=_definition_response_format(values),
        temperature=temperature,
        deadline_monotonic=deadline_monotonic,
    )
    return _parse_definitions_json(text, values)


def fill_classification_definitions(
    complete_fn: Callable[..., str],
    column_name: str,
    values: List[str],
    facts: Dict[str, Any],
    *,
    compact: bool = False,
    deadline_monotonic: Optional[float] = None,
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Fill definitions for classification values; merge batches independently.

    Returns ``(definitions, batch_errors)``. A failed later batch does not discard
    definitions already filled by earlier batches.
    """
    if not values:
        return {}, []

    batch_size = DEFINITION_BATCH_SIZE_COMPACT if compact else DEFINITION_BATCH_SIZE
    if deadline_monotonic is None:
        deadline_monotonic = time.monotonic() + DEFINITION_COLUMN_DEADLINE_SEC

    out: Dict[str, str] = {}
    errors: List[Dict[str, Any]] = []

    for i in range(0, len(values), batch_size):
        batch = values[i : i + batch_size]
        batch_index = i // batch_size
        try:
            out.update(
                _fill_classification_definitions_batch(
                    complete_fn,
                    column_name,
                    batch,
                    facts,
                    compact=compact,
                    deadline_monotonic=deadline_monotonic,
                )
            )
        except Exception as e:
            msg = str(e).strip() or e.__class__.__name__
            errors.append({
                "column": column_name,
                "batch": batch_index,
                "values_start": i,
                "values_count": len(batch),
                "error": msg,
            })
            # Stop further batches only when the shared deadline is exhausted.
            remaining = deadline_monotonic - time.monotonic()
            if remaining < 8.0:
                break
            continue

    return out, errors


def resolve_definitions_compact(
    *,
    self_hosted: bool,
    model: Optional[str] = None,
) -> bool:
    """Same compact selection as metadata autofill (incl. DHARA_METADATA_COMPACT)."""
    return use_compact_metadata_prompt(self_hosted=self_hosted, model=model)


__all__ = [
    "DEFINITION_BATCH_SIZE",
    "DEFINITION_BATCH_SIZE_COMPACT",
    "DEFINITION_COLUMN_DEADLINE_SEC",
    "fill_classification_definitions",
    "resolve_definitions_compact",
]
