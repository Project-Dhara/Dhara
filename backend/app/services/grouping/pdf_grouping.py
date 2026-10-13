"""
PDF Stage 5–7: propose table groups for human review.

Orchestrator + thin re-exports. Implementation split across embeddings,
sdg_groups, and singleton_merge.
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
    _cluster_by_distance,
    _groups_from_clusters,
    _load_summary_embeddings,
    _propose_title_groups,
    _pseudo_embedding,
    build_column_chunks,
    build_table_summary_chunk,
    embed_texts,
    index_tables,
)

from app.services.grouping.sdg_groups import (
    _propose_sdg_groups,
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
      - optional strict LLM merge of remaining titled singletons when api_key set

    Each input table must be identifiable via ``id``, ``_uid``, or ``table_id``.
    """
    if not tables:
        return {
            "groups": [],
            "unmatched_tables": [],
            "method": "empty",
            "indexed": 0,
        }

    normalized: list[dict] = []
    for i, raw in enumerate(tables):
        t = dict(raw or {})
        tid = t.get("id") or t.get("_uid") or t.get("table_id") or f"row-{i}"
        t["id"] = str(tid)
        if not t.get("_uid"):
            t["_uid"] = t["id"]
        normalized.append(t)

    embeddings = embeddings or {}
    if corpus_looks_like_sdg_indicator_tables(normalized):
        if embeddings:
            groups = _propose_sdg_groups(normalized, embeddings, threshold)
        else:
            # No vectors available (Excel/SQL): SDG buckets + title groups for leftovers.
            by_goal: dict[int, list[dict]] = defaultdict(list)
            leftovers: list[dict] = []
            for t in normalized:
                goal = detect_sdg_goal(t)
                if goal is not None:
                    by_goal[goal].append(t)
                else:
                    leftovers.append(t)
            groups = []
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
        method = "sdg_goal"
    else:
        groups = _propose_title_groups(normalized)
        method = "title_base"
        if embeddings:
            untitled_groups = [
                g for g in groups if (g.get("name") or "").startswith("Untitled (")
            ]
            titled_groups = [
                g for g in groups if not (g.get("name") or "").startswith("Untitled (")
            ]
            leftovers = [m for g in untitled_groups for m in (g.get("tables") or [])]
            if len(leftovers) >= 2:
                by_id = {t["id"]: t for t in leftovers}
                clusters = _cluster_by_distance(
                    [t["id"] for t in leftovers],
                    embeddings,
                    threshold,
                )
                titled_groups.extend(
                    _groups_from_clusters(clusters, by_id, name_start_index=len(titled_groups))
                )
                groups = titled_groups
                method = "title_base+embed_untitled"

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

    Prefer title-base buckets (Excel parity). SDG indicator corpora still use
    goal numbers. Embeddings are only used to cluster untitled leftovers when
    reindex/embeddings are available. Remaining titled singletons may be
    strictly merged by LLM when an API key is available.

    ``session`` is a SQLAlchemy Session for tables and vector index I/O.
    """
    from app.storage import vectors as vs

    tables = pdf_store.list_active_tables(session, job_id)
    if not tables:
        return {
            "groups": [],
            "unmatched_tables": [],
            "method": "empty",
            "indexed": 0,
        }

    indexed = 0
    embeddings: dict[str, list[float]] = {}
    key = (api_key or "").strip() or None

    if corpus_looks_like_sdg_indicator_tables(tables):
        embeddings = _load_summary_embeddings(session, job_id)
        missing = [t for t in tables if t["id"] not in embeddings]
        if reindex or missing:
            indexed = index_tables(
                session, job_id, tables if reindex else missing, api_key=key
            )
            embeddings = _load_summary_embeddings(session, job_id)
        if len(embeddings) < len(tables):
            for t in tables:
                if t["id"] not in embeddings:
                    embeddings[t["id"]] = _pseudo_embedding(
                        build_table_summary_chunk(t), vs.embedding_dim()
                    )
        result = propose_groups_from_table_dicts(
            tables, embeddings=embeddings, threshold=threshold, api_key=key
        )
        result["indexed"] = indexed
        return result

    result = propose_groups_from_table_dicts(tables, threshold=threshold)
    groups = result.get("groups") or []
    untitled_groups = [
        g for g in groups if (g.get("name") or "").startswith("Untitled (")
    ]
    leftovers = [m for g in untitled_groups for m in (g.get("tables") or [])]
    if len(leftovers) >= 2:
        embeddings = _load_summary_embeddings(session, job_id)
        missing = [t for t in leftovers if t["id"] not in embeddings]
        if reindex or missing:
            indexed = index_tables(
                session,
                job_id,
                tables if reindex else leftovers,
                api_key=key,
            )
            embeddings = _load_summary_embeddings(session, job_id)
        for t in leftovers:
            if t["id"] not in embeddings:
                embeddings[t["id"]] = _pseudo_embedding(
                    build_table_summary_chunk(t), vs.embedding_dim()
                )
        result = propose_groups_from_table_dicts(
            tables, embeddings=embeddings, threshold=threshold, api_key=key
        )
        result["indexed"] = indexed
        return result

    # Title-base result is final structurally; optional strict singleton LLM merge.
    groups, llm_merged = merge_singleton_groups_strict(groups, api_key=key)
    if llm_merged:
        method = result.get("method") or "title_base"
        result["method"] = f"{method}+llm_singletons_strict"
        groups.sort(key=lambda g: (-len(g["tables"]), (g.get("name") or "").lower()))
        result["groups"] = groups
    result["indexed"] = indexed
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
