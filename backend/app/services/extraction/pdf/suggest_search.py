"""Natural-language table search / remove-selection for the Preview list."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from app.services.llm_prompts import OPENAI_MODEL, TABLE_AI_SEARCH_PROMPT

logger = logging.getLogger(__name__)

_REMOVE_HINT = re.compile(
    r"\b(remove|delete|drop|discard|exclude|get rid of|take out)\b",
    re.IGNORECASE,
)


def _catalog_entry(table: Dict[str, Any]) -> Dict[str, Any]:
    title = str(table.get("title") or "").strip()
    banner = str(table.get("banner_table_id") or "").strip()
    summary = str(
        table.get("short_description")
        or table.get("description")
        or table.get("summary")
        or ""
    ).strip()
    label = title or banner or f"Page {table.get('page')} table"
    entry = {
        "table_id": str(table.get("table_id") or ""),
        "page": table.get("page"),
        "title": label,
    }
    if summary:
        entry["summary"] = summary[:240]
    return entry


def _sanitize_ids(ids_raw: Any, valid_ids: set[str]) -> List[str]:
    selected: List[str] = []
    if not isinstance(ids_raw, list):
        return selected
    seen: set[str] = set()
    for tid in ids_raw:
        sid = str(tid or "").strip()
        if not sid or sid not in valid_ids or sid in seen:
            continue
        seen.add(sid)
        selected.append(sid)
    return selected


def suggest_tables_from_prompt(
    *,
    prompt: str,
    tables: List[Dict[str, Any]],
    api_key: str,
) -> Dict[str, Any]:
    """Ask the LLM which catalog tables match a find or remove instruction.

    Returns ``{"intent": "find"|"remove", "table_ids": [...], "rationale": "..."}``.
    Defaults to ``find`` unless the prompt clearly asks to remove tables —
    ordinary search queries must not enter a destructive selection path.
    """
    text = (prompt or "").strip()
    if not text:
        raise ValueError("prompt is required")
    if not (api_key or "").strip():
        raise ValueError("An LLM API key is required in Settings")

    catalog = [_catalog_entry(t) for t in tables if t.get("table_id") is not None]
    valid_ids = {str(c["table_id"]) for c in catalog if c["table_id"]}
    if not valid_ids:
        return {
            "intent": "find",
            "table_ids": [],
            "rationale": "No tables are available.",
        }

    from openai import OpenAI

    user_prompt = TABLE_AI_SEARCH_PROMPT.format(
        prompt=text,
        catalog_json=json.dumps(catalog, ensure_ascii=False),
    )
    client = OpenAI(api_key=api_key.strip())
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=2000,
        temperature=0,
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.warning("suggest_search: non-JSON LLM response: %s", raw[:300])
        return {
            "intent": "find",
            "table_ids": [],
            "rationale": "Could not parse the model response.",
        }

    if not isinstance(data, dict):
        data = {}

    intent_raw = str(data.get("intent") or "").strip().lower()
    # Prefer find unless the steward clearly asked to remove AND the model
    # agreed — avoids turning a normal search into delete selection.
    wants_remove = bool(_REMOVE_HINT.search(text)) and intent_raw == "remove"
    intent = "remove" if wants_remove else "find"

    selected = _sanitize_ids(data.get("table_ids"), valid_ids)
    rationale = str(data.get("rationale") or "").strip()
    if not rationale:
        if selected:
            rationale = f"Matched {len(selected)} table(s)."
        else:
            rationale = "No matching tables."

    return {
        "intent": intent,
        "table_ids": selected,
        "rationale": rationale,
    }
