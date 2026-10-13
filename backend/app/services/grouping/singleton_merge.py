"""Strict singleton re-merge for leftover PDF table groups."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from app.services.grouping.matching import _base_title, build_group_name

from app.services.grouping.embeddings import (
    _suggest_group_name,
)

GROUP_LLM_MODEL = os.environ.get("PDF_GROUP_LLM_MODEL", "gpt-4o-mini")

_SINGLETON_MIN_SHARED_TOKENS = int(os.environ.get("PDF_GROUP_SINGLETON_SHARED", "2"))

_SINGLETON_CONTAINMENT_RATIO = float(os.environ.get("PDF_GROUP_SINGLETON_CONTAINMENT", "0.7"))

_SINGLETON_LLM_BATCH = int(os.environ.get("PDF_GROUP_SINGLETON_BATCH", "36"))

_TITLE_STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "by", "for", "in", "on", "to", "with",
    "as", "at", "from", "per", "no", "sl", "nos", "table", "statement",
}

_VARIANT_TOKENS = {
    "urban", "rural", "all", "total", "male", "female", "others", "other",
}

def _significant_title_tokens(title: str) -> set[str]:
    """Content tokens for overlap checks (drop stopwords / URBAN|RURAL)."""
    base = _base_title(title or "")
    tokens = re.findall(r"[a-z0-9]+", base.lower())
    out = set()
    for tok in tokens:
        if len(tok) < 3:
            continue
        if tok in _TITLE_STOPWORDS or tok in _VARIANT_TOKENS:
            continue
        if tok.isdigit():
            continue
        out.add(tok)
    return out

def _title_token_jaccard(a: str, b: str) -> float:
    ta, tb = _significant_title_tokens(a), _significant_title_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0

def _titles_pair_compatible(a: str, b: str) -> bool:
    """Accurate lexical check: enough shared tokens or title containment."""
    ta, tb = _significant_title_tokens(a), _significant_title_tokens(b)
    if not ta or not tb:
        return False
    inter = ta & tb
    if len(inter) >= _SINGLETON_MIN_SHARED_TOKENS:
        return True
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not smaller:
        return False
    return (len(smaller & larger) / len(smaller)) >= _SINGLETON_CONTAINMENT_RATIO and len(inter) >= 1

def _titles_strictly_compatible(titles: list[str]) -> bool:
    """Every pair must pass the lexical gate."""
    cleaned = [str(t or "").strip() for t in titles if str(t or "").strip()]
    if len(cleaned) < 2:
        return False
    for i in range(len(cleaned)):
        for j in range(i + 1, len(cleaned)):
            if not _titles_pair_compatible(cleaned[i], cleaned[j]):
                return False
    return True

def _column_name_preview(table: dict, limit: int = 6) -> list[str]:
    names: list[str] = []
    for col in (table.get("columns") or [])[:limit]:
        if isinstance(col, dict):
            n = str(col.get("name") or "").strip()
        else:
            n = str(col or "").strip()
        if n:
            names.append(n)
    return names

def _call_singleton_merge_llm(
    items: list[dict[str, Any]],
    *,
    api_key: str,
) -> list[dict[str, Any]]:
    """Ask the model for merges among singleton titles. Uses short surrogate ids."""
    from openai import OpenAI

    # Short ids (t1, t2, …) — UUIDs / long catalogue ids are often mangled.
    alias_to_real: dict[str, str] = {}
    catalog = []
    real_ids = {str(it["id"]) for it in items}
    for i, it in enumerate(items):
        alias = f"t{i + 1}"
        alias_to_real[alias] = str(it["id"])
        entry: dict[str, Any] = {"id": alias, "title": it["title"]}
        cols = it.get("columns") or []
        if cols:
            entry["columns"] = cols
        catalog.append(entry)

    prompt = f"""You are grouping statistical tables from an Indian government report.
These tables are currently alone after exact title matching. Merge them into
accurate groups where titles clearly belong to the SAME logical table family.

MERGE when:
- Same subject/measure with geography or population variants (URBAN/RURAL/ALL,
  male/female, etc.) that exact-match missed due to wording differences
- Near-identical captions with a small qualifier difference
- Clear series of the same indicator (e.g. same birth/death topic with closely
  related breakdowns that a steward would put on one metadata card)

DO NOT merge when:
- Titles only share a broad domain (e.g. both "about births" but different
  primary indicators or unrelated breakdowns)
- Different SDG goals or unrelated measures

Be decisive: if two titles clearly belong together, merge them with
confidence "high". If unsure, leave them out of merges.

Return ONLY valid JSON (no markdown):
{{
  "merges": [
    {{
      "table_ids": ["t1", "t2"],
      "name": "short shared group name",
      "confidence": "high"
    }}
  ]
}}

Rules:
- confidence must be exactly "high" for every merge you include
- each id in at most one merge; every merge has >= 2 catalog ids
- use only ids from the catalog (t1, t2, …); never invent ids
- omit tables that should stay alone

Catalog:
{json.dumps(catalog, ensure_ascii=False)}
"""

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=GROUP_LLM_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
        max_tokens=6000,
        temperature=0,
    )
    text = (resp.choices[0].message.content or "").strip()
    data = json.loads(text) if text else {}
    merges = data.get("merges") if isinstance(data, dict) else None
    if not isinstance(merges, list):
        return []

    out: list[dict[str, Any]] = []
    for m in merges:
        if not isinstance(m, dict):
            continue
        ids_raw = m.get("table_ids") or m.get("ids") or []
        if not isinstance(ids_raw, list):
            continue
        mapped: list[str] = []
        for x in ids_raw:
            alias = str(x or "").strip()
            real = alias_to_real.get(alias) or alias_to_real.get(alias.lower())
            if not real and alias in real_ids:
                real = alias
            if real and real not in mapped:
                mapped.append(real)
        if len(mapped) < 2:
            continue
        out.append(
            {
                "table_ids": mapped,
                "name": m.get("name"),
                "confidence": m.get("confidence"),
            }
        )
    return out

def _call_singleton_merge_llm_batched(
    items: list[dict[str, Any]],
    *,
    api_key: str,
) -> list[dict[str, Any]]:
    """Sort by title and batch so similar captions share a window."""
    ordered = sorted(items, key=lambda it: str(it.get("title") or "").lower())
    batch_n = max(8, _SINGLETON_LLM_BATCH)
    if len(ordered) <= batch_n:
        return _call_singleton_merge_llm(ordered, api_key=api_key)

    merges: list[dict[str, Any]] = []
    step = max(6, batch_n - 8)
    for start in range(0, len(ordered), step):
        batch = ordered[start : start + batch_n]
        if len(batch) < 2:
            break
        merges.extend(_call_singleton_merge_llm(batch, api_key=api_key))
        if start + batch_n >= len(ordered):
            break
    return merges

def _validate_singleton_merges(
    merges: list[dict[str, Any]],
    singleton_by_id: dict[str, dict],
) -> list[list[str]]:
    """Keep only high-confidence, structurally valid, lexically compatible merges."""
    used: set[str] = set()
    accepted: list[list[str]] = []
    for raw in merges:
        conf = str(raw.get("confidence") or "").strip().lower()
        if conf != "high":
            continue
        ids_raw = raw.get("table_ids") or raw.get("ids") or []
        if not isinstance(ids_raw, list):
            continue
        ids: list[str] = []
        for x in ids_raw:
            tid = str(x or "").strip()
            if not tid or tid not in singleton_by_id or tid in used:
                continue
            if tid not in ids:
                ids.append(tid)
        if len(ids) < 2:
            continue
        titles = [
            str((singleton_by_id[tid].get("tables") or [{}])[0].get("title") or "")
            for tid in ids
        ]
        if not _titles_strictly_compatible(titles):
            continue
        for tid in ids:
            used.add(tid)
        accepted.append(ids)
    return accepted

def merge_singleton_groups_strict(
    groups: list[dict],
    *,
    api_key: Optional[str] = None,
) -> tuple[list[dict], bool]:
    """
    LLM pass over size-1 groups only. Multi-member groups are untouched.

    Returns (possibly updated groups, whether any merge was applied).
    On missing key / API failure / empty singletons, returns groups unchanged.
    """
    key = (api_key or "").strip()
    if not key or not groups:
        print(
            f"[pdf_grouping] singleton LLM skipped (key={'yes' if bool(key) else 'no'}, groups={len(groups or [])})",
            flush=True,
        )
        return groups, False

    multi: list[dict] = []
    singletons: list[dict] = []
    for g in groups:
        members = g.get("tables") or []
        if len(members) == 1 and str((members[0] or {}).get("title") or "").strip():
            singletons.append(g)
        else:
            multi.append(g)

    if len(singletons) < 2:
        print(
            f"[pdf_grouping] singleton LLM skipped (singletons={len(singletons)})",
            flush=True,
        )
        return groups, False

    singleton_by_id: dict[str, dict] = {}
    items: list[dict[str, Any]] = []
    for g in singletons:
        t = (g.get("tables") or [None])[0] or {}
        tid = str(t.get("id") or "")
        if not tid:
            continue
        singleton_by_id[tid] = g
        items.append(
            {
                "id": tid,
                "title": str(t.get("title") or "").strip(),
                "columns": _column_name_preview(t),
            }
        )

    if len(items) < 2:
        return groups, False

    try:
        raw_merges = _call_singleton_merge_llm_batched(items, api_key=key)
    except Exception as exc:
        print(f"[pdf_grouping] singleton LLM merge skipped ({exc})", flush=True)
        return groups, False

    accepted = _validate_singleton_merges(raw_merges, singleton_by_id)
    print(
        f"[pdf_grouping] singleton LLM: candidates={len(items)} "
        f"proposed={len(raw_merges)} accepted={len(accepted)}",
        flush=True,
    )
    if not accepted:
        return groups, False

    merged_ids: set[str] = set()
    new_groups: list[dict] = list(multi)
    for i, ids in enumerate(accepted):
        members = []
        for tid in ids:
            g = singleton_by_id[tid]
            members.extend(g.get("tables") or [])
            merged_ids.add(tid)
        name = _suggest_group_name(members, len(new_groups) + i)
        new_groups.append(
            {
                "name": name,
                "tables": members,
                "table_pks": [m["id"] for m in members],
            }
        )

    for tid, g in singleton_by_id.items():
        if tid not in merged_ids:
            new_groups.append(g)

    return new_groups, True

__all__ = [
    "merge_singleton_groups_strict",
    "_titles_pair_compatible",
    "_titles_strictly_compatible",
    "_validate_singleton_merges",
    "_call_singleton_merge_llm",
    "_call_singleton_merge_llm_batched",
]
