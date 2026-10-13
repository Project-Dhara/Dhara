"""Embedding / clustering helpers for PDF table grouping."""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections import defaultdict
from typing import Any, Optional

from app.storage import vectors as vs
from app.services.grouping.matching import _base_title, build_group_name

EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

DEFAULT_DISTANCE_THRESHOLD = float(os.environ.get("PDF_GROUP_DISTANCE", "0.42"))

TOP_K = int(os.environ.get("PDF_GROUP_TOP_K", "8"))

def build_table_summary_chunk(table: dict) -> str:
    """Text used for leftover embedding fallback — title only (not subject)."""
    title = str(table.get("title") or "").strip()
    if title:
        return title
    # Untitled tables: fall back to a thin structural cue so they don't all
    # collapse into one embedding neighbourhood.
    parts = [
        table.get("table_id") or table.get("id") or "",
        table.get("domain") or "",
        table.get("entity") or "",
        table.get("table_type") or "",
    ]
    return " | ".join(p for p in parts if p and str(p).strip())

def build_column_chunks(table: dict, limit: int = 12) -> list[tuple[str, str]]:
    """Return [(chunk_kind_suffix, text), ...] for important columns."""
    out = []
    cols = table.get("columns") or []
    for i, col in enumerate(cols[:limit]):
        if not isinstance(col, dict):
            continue
        name = col.get("name") or col.get("value") or f"col_{i}"
        role = col.get("role")
        if isinstance(role, dict):
            role = role.get("value")
        concept = col.get("concept")
        if isinstance(concept, dict):
            concept = concept.get("value")
        text = " | ".join(str(x) for x in (name, role, concept) if x)
        if text.strip():
            out.append((f"column_meaning:{i}", text.strip()))
    return out

def _pseudo_embedding(text: str, dim: int) -> list[float]:
    """Deterministic bag-of-tokens vector when OpenAI embeddings are unavailable."""
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    if not tokens:
        tokens = ["empty"]
    for tok in tokens:
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        for i in range(0, min(32, dim), 4):
            idx = int.from_bytes(h[i : i + 4], "big") % dim
            vec[idx] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]

def embed_texts(texts: list[str], api_key: Optional[str] = None) -> list[list[float]]:
    dim = vs.embedding_dim()
    # Settings-scoped key only — never fall back to server OPENAI_API_KEY.
    key = (api_key or "").strip()
    if not key or not texts:
        return [_pseudo_embedding(t, dim) for t in texts]
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            chunk = texts[i : i + 64]
            resp = client.embeddings.create(model=EMBED_MODEL, input=chunk)
            by_idx = {d.index: d.embedding for d in resp.data}
            out.extend(by_idx[j] for j in range(len(chunk)))
        return out
    except Exception as exc:
        print(f"[pdf_grouping] embeddings fallback ({exc})", flush=True)
        return [_pseudo_embedding(t, dim) for t in texts]

def index_tables(session, job_id: str, tables: list[dict], api_key: Optional[str] = None) -> int:
    """Chunk + upsert embeddings for tables. Returns number of summary chunks written."""
    vs.ensure_semantic_embeddings_table(session)
    summaries = [build_table_summary_chunk(t) for t in tables]
    vectors = embed_texts(summaries, api_key=api_key)
    n = 0
    for table, text, emb in zip(tables, summaries, vectors):
        if not text.strip():
            text = table.get("table_id") or table.get("id") or "untitled"
        vs.upsert_embedding(
            session,
            object_type="pdf_table",
            object_id=table["id"],
            chunk_kind="table_summary",
            chunk_text=text,
            embedding=emb,
            metadata={"job_id": job_id, "table_id": table.get("table_id"), "title": table.get("title")},
            job_id=job_id,
        )
        n += 1

        col_chunks = build_column_chunks(table)
        if col_chunks:
            col_texts = [c[1] for c in col_chunks]
            col_vecs = embed_texts(col_texts, api_key=api_key)
            for (kind, ctext), cemb in zip(col_chunks, col_vecs):
                vs.upsert_embedding(
                    session,
                    object_type="pdf_table",
                    object_id=table["id"],
                    chunk_kind=kind,
                    chunk_text=ctext,
                    embedding=cemb,
                    metadata={"job_id": job_id, "table_id": table.get("table_id")},
                    job_id=job_id,
                )
    return n

def _load_summary_embeddings(session, job_id: str) -> dict[str, list[float]]:
    """object_id → embedding vector for table_summary chunks in this job."""
    from sqlalchemy import text as sa_text

    rows = session.execute(
        sa_text(
            """
            SELECT object_id::text, embedding::text
              FROM semantic_embeddings
             WHERE chunk_kind = 'table_summary'
               AND object_type = 'pdf_table'
               AND (job_id = :job_id OR metadata->>'job_id' = :job_id)
            """
        ),
        {"job_id": job_id},
    ).all()
    out: dict[str, list[float]] = {}
    for oid, emb in rows:
        if emb is None:
            continue
        if hasattr(emb, "tolist"):
            out[str(oid)] = list(emb.tolist())
        elif isinstance(emb, (list, tuple)):
            out[str(oid)] = list(emb)
        else:
            s = str(emb).strip()
            if s.startswith("["):
                out[str(oid)] = [
                    float(x) for x in s[1:-1].split(",") if x.strip()
                ]
    return out

def _cosine_distance(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 1.0
    return 1.0 - (dot / (na * nb))

def _cluster_by_distance(
    table_ids: list[str],
    embeddings: dict[str, list[float]],
    threshold: float,
) -> list[list[str]]:
    """Union-find clustering: connect pairs under distance threshold."""
    parent = {tid: tid for tid in table_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, a in enumerate(table_ids):
        ea = embeddings.get(a)
        if not ea:
            continue
        # Compare to a limited neighbourhood of closest others
        dists = []
        for b in table_ids:
            if a == b:
                continue
            eb = embeddings.get(b)
            if not eb:
                continue
            dists.append((_cosine_distance(ea, eb), b))
        dists.sort(key=lambda x: x[0])
        for dist, b in dists[:TOP_K]:
            if dist <= threshold:
                union(a, b)

    buckets: dict[str, list[str]] = defaultdict(list)
    for tid in table_ids:
        buckets[find(tid)].append(tid)
    # Singletons stay as their own groups (user can merge); keep all clusters
    return list(buckets.values())

def _suggest_group_name(members: list[dict], index: int) -> str:
    # Prefer shared base title (Excel-style), never subject — subject is often
    # a coarse LLM label that collapses unrelated tables into one bucket.
    bases = []
    for m in members:
        title = str(m.get("title") or "").strip()
        if title:
            bases.append(_base_title(title))
    if bases:
        best = max(set(bases), key=bases.count)
        if best:
            return _clean_group_display_name(build_group_name(best))[:120]
    for key in ("domain", "entity", "title"):
        vals = [str(m.get(key) or "").strip() for m in members]
        vals = [v for v in vals if v]
        if not vals:
            continue
        best = max(set(vals), key=vals.count)
        if best:
            return _clean_group_display_name(best)[:80]
    return f"Group {index + 1}"

def _propose_title_groups(tables: list[dict]) -> list[dict]:
    """
    Group by normalized title, same rule as Excel ``auto_group_tables``:
    strip a trailing parenthetical qualifier so URBAN/RURAL/ALL variants
    of the same caption share a group.
    """
    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    untitled: list[dict] = []

    for t in tables:
        title = str(t.get("title") or "").strip()
        if not title:
            untitled.append(t)
            continue
        key = _base_title(title)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(t)

    groups: list[dict] = []
    for i, key in enumerate(order):
        members = buckets[key]
        name = _clean_group_display_name(build_group_name(key))[:120]
        groups.append(
            {
                "name": name or f"Group {i + 1}",
                "tables": members,
                "table_pks": [m["id"] for m in members],
            }
        )

    # Untitled leftovers: each alone (caller may re-cluster via embeddings).
    for j, t in enumerate(untitled):
        label = str(t.get("table_id") or t.get("id") or j + 1)
        groups.append(
            {
                "name": f"Untitled ({label})",
                "tables": [t],
                "table_pks": [t["id"]],
            }
        )
    return groups

_PAGES_IN_TITLE_RE = re.compile(
    r"\s*\(\s*pages?\s+\d+(?:\s*[–—\-]\s*\d+)?\s*\)\s*$",
    re.IGNORECASE,
)

def _clean_group_display_name(name: str) -> str:
    cleaned = _PAGES_IN_TITLE_RE.sub("", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
    return cleaned or (name or "").strip()

def _groups_from_clusters(
    clusters: list[list[str]],
    by_id: dict[str, dict],
    name_start_index: int = 0,
) -> list[dict]:
    groups = []
    for i, member_ids in enumerate(clusters):
        members = [by_id[m] for m in member_ids if m in by_id]
        if not members:
            continue
        name = _suggest_group_name(members, name_start_index + i)
        groups.append(
            {"name": name, "tables": members, "table_pks": [m["id"] for m in members]}
        )
    return groups

__all__ = [
    "DEFAULT_DISTANCE_THRESHOLD",
    "EMBED_MODEL",
    "TOP_K",
    "_clean_group_display_name",
    "_cluster_by_distance",
    "_groups_from_clusters",
    "_load_summary_embeddings",
    "_propose_title_groups",
    "build_column_chunks",
    "build_table_summary_chunk",
    "embed_texts",
    "index_tables",
]
