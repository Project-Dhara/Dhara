"""LLM-backed classification definition fill."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

def fill_classification_definitions(
    complete_fn: Callable[[str, int], str],
    column_name: str,
    values: List[str],
    facts: Dict[str, Any],
) -> Dict[str, str]:
    """One-sentence definitions for classification values, grounded in catalogue/excel facts."""
    if not values:
        return {}
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
    text = complete_fn(prompt, min(800, 160 + 40 * len(values)))
    text = re.sub(r"```[a-zA-Z]*\n?", "", text).strip().rstrip("`")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        return {}
    out = {}
    for v in values:
        d = parsed.get(v)
        if d is None:
            d = next((parsed[k] for k in parsed if str(k).strip().lower() == str(v).strip().lower()), None)
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

__all__ = [
    "fill_classification_definitions",
]
