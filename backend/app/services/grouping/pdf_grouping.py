"""
PDF Stage 5–7: propose table groups for human review.

Orchestrator + thin re-exports. Implementation split across embeddings,
sdg_groups, and singleton_merge.

Grouping never calls OpenAI/remote embeddings. Untitled tables stay singletons
in finished groups; optional suggested_merges require steward confirm.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

from app.db.repositories import pdf_jobs as pdf_store
from app.services.grouping.matching import _base_title, build_group_name

from app.services.grouping.embeddings import (
    DEFAULT_DISTANCE_THRESHOLD,
    EMBED_MODEL,
    TOP_K,
    _propose_title_groups,
    build_column_chunks,
    build_table_summary_chunk,
    embed_texts,
    index_tables,
    suggest_untitled_merges,
)

from app.services.grouping.sdg_groups import (
    corpus_looks_like_sdg_indicator_tables,
    detect_sdg_goal,
)

from app.services.grouping.singleton_merge import (
    GROUP_LLM_MODEL,
    _call_singleton_merge_llm,
    _call_singleton_merge_llm_batched,
    _titles_pair_compatible,
    _titles_strictly_compatible,
    _validate_singleton_merges,
    merge_singleton_groups_strict,
)


def _sdg_groups_without_embed_clusters(tables: list[dict]) -> list[dict]:
    """SDG goal buckets; leftovers use title groups (untitled stay singletons)."""
    by_goal: dict[int, list[dict]] = defaultdict(list)
    leftovers: list[dict] = []
    for t in tables:
        goal = detect_sdg_goal(t)
        if goal is not None:
            by_goal[goal].append(t)
        else:
            leftovers.append(t)
    groups: list[dict] = []
    for goal in sorted(by_goal.keys()):
        members = by_goal[goal]
        groups.append(
            {
                "name": f"SDG {goal}",
                "tables": members,
                "table_pks": [m["id"] for m in members],
            }
        )
    if leftovers:
        groups.extend(_propose_title_groups(leftovers))
    return groups


def propose_groups_from_table_dicts(
    tables: list[dict],
    *,
    embeddings: Optional[dict[str, list[float]]] = None,
    threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    api_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    In-memory grouping used by every upload format (PDF / Excel / SQL).

    Same rules as ``propose_groups`` for a PDF job, without requiring Postgres:
      - SDG corpora → goal buckets (leftovers fall back to title groups)
      - otherwise → base-title buckets (URBAN/RURAL/ALL variants merge)
      - untitled tables remain singletons (no embedding auto-merge)
      - optional strict LLM merge of remaining titled singletons when api_key set
      - ``suggested_merges`` for untitled structural cues (steward must confirm)

    ``embeddings`` is ignored for finished-group formation (compat only).
    """
    del embeddings  # never bake embedding/pseudo clusters into finished groups
    if not tables:
        return {
            "groups": [],
            "unmatched_tables": [],
            "method": "empty",
            "indexed": 0,
            "suggested_merges": [],
        }

    normalized: list[dict] = []
    for i, raw in enumerate(tables):
        t = dict(raw or {})
        tid = t.get("id") or t.get("_uid") or t.get("table_id") or f"row-{i}"
        t["id"] = str(tid)
        if not t.get("_uid"):
            t["_uid"] = t["id"]
        normalized.append(t)

    if corpus_looks_like_sdg_indicator_tables(normalized):
        groups = _sdg_groups_without_embed_clusters(normalized)
        method = "sdg_goal"
    else:
        groups = _propose_title_groups(normalized)
        method = "title_base"

    groups, llm_merged = merge_singleton_groups_strict(groups, api_key=api_key)
    if llm_merged:
        method = f"{method}+llm_singletons_strict"

    groups.sort(key=lambda g: (-len(g["tables"]), (g.get("name") or "").lower()))
    if method.startswith("sdg_goal"):
        def _sdg_sort_key(g: dict) -> tuple:
            m = re.match(r"^SDG\s+(\d+)$", g.get("name") or "", re.IGNORECASE)
            if m:
                return (0, int(m.group(1)))
            return (1, 0, (g.get("name") or "").lower())

        groups.sort(key=_sdg_sort_key)

    return {
        "groups": groups,
        "unmatched_tables": [],
        "method": method,
        "indexed": 0,
        "threshold": threshold,
        "suggested_merges": suggest_untitled_merges(normalized),
    }


def proposal_to_catalogue_match_result(
    proposal: dict,
    *,
    source_type: str = "xlsx",
    default_source_file: str = "Dataset",
) -> dict[str, Any]:
    """Convert PDF-style ``{groups:[{name, tables}]}`` into batch-match shape."""
    empty_meta = {
        "title": "", "product": "", "category": "", "geography": "",
        "frequency": "", "time_period": "", "data_source": "", "description": "",
        "last_updated": "", "future_release": "", "key_statistics": "", "remarks": "",
    }
    out_groups = []
    for wi, g in enumerate(proposal.get("groups") or []):
        members = []
        for t in g.get("tables") or []:
            table = dict(t)
            uid = table.get("_uid") or table.get("id") or table.get("table_id")
            table["_uid"] = uid
            table.setdefault("source_type", source_type)
            table.setdefault(
                "source_file",
                table.get("source_file") or table.get("filename") or default_source_file,
            )
            table.setdefault("sheet", table.get("sheet") or table.get("title") or "data")
            members.append(
                {
                    "table": table,
                    "inventory_item": None,
                    "confidence": source_type if source_type == "pdf" else "title_base",
                }
            )
        out_groups.append(
            {
                "workbook_index": wi,
                "file_name": g.get("name") or f"Group {wi + 1}",
                "metadata": dict(empty_meta),
                "concepts": [],
                "classifications": {},
                "matched_tables": members,
            }
        )
    return {
        "groups": out_groups,
        "unmatched_tables": [],
        "unmatched_inventory": [],
        "method": proposal.get("method"),
        "suggested_merges": proposal.get("suggested_merges") or [],
    }


def propose_groups(
    session,
    job_id: str,
    *,
    threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    api_key: Optional[str] = None,
    reindex: bool = False,
) -> dict[str, Any]:
    """
    Propose grouping for a PDF job.

    Prefer title-base buckets (Excel parity). SDG indicator corpora use goal
    numbers. Untitled tables stay singletons; optional ``suggested_merges`` use
    strict structural cues. Titled singletons may be strictly merged by chat LLM
    when an API key is available. Never calls remote embeddings.
    """
    del reindex  # no embedding reindex for finished groups

    tables = pdf_store.list_active_tables(session, job_id)
    if not tables:
        return {
            "groups": [],
            "unmatched_tables": [],
            "method": "empty",
            "indexed": 0,
            "suggested_merges": [],
        }

    key = (api_key or "").strip() or None
    result = propose_groups_from_table_dicts(
        tables, threshold=threshold, api_key=key
    )
    result["indexed"] = 0
    return result


def apply_proposal_to_db(session, job_id: str, proposal: dict) -> dict:
    """Persist proposal via pdf_jobs.save_grouping and return load_grouping shape."""
    groups_payload = [
        {"name": g["name"], "table_pks": g.get("table_pks") or [t["id"] for t in g.get("tables") or []]}
        for g in proposal.get("groups") or []
    ]
    pdf_store.save_grouping(session, job_id=job_id, groups=groups_payload)
    loaded = pdf_store.load_grouping(session, job_id)
    loaded["method"] = proposal.get("method")
    loaded["indexed"] = proposal.get("indexed", 0)
    loaded["threshold"] = proposal.get("threshold")
    # Suggestions are not SoT — attach for steward confirm UI only.
    loaded["suggested_merges"] = list(proposal.get("suggested_merges") or [])
    return loaded


__all__ = [
    "apply_proposal_to_db",
    "propose_groups",
    "propose_groups_from_table_dicts",
    "proposal_to_catalogue_match_result",
    "build_table_summary_chunk",
    "build_column_chunks",
    "embed_texts",
    "index_tables",
    "detect_sdg_goal",
    "corpus_looks_like_sdg_indicator_tables",
    "merge_singleton_groups_strict",
    "suggest_untitled_merges",
    "_titles_pair_compatible",
    "_titles_strictly_compatible",
    "_validate_singleton_merges",
    "_call_singleton_merge_llm",
    "_call_singleton_merge_llm_batched",
    "EMBED_MODEL",
    "DEFAULT_DISTANCE_THRESHOLD",
    "TOP_K",
    "GROUP_LLM_MODEL",
]
