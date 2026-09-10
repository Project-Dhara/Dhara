"""
PDF Stage 5–7: semantic chunks → embeddings → similarity grouping proposals.

pgvector finds candidate neighbours; clustering produces draft groups.
Human review (frontend) remains authoritative.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections import defaultdict
from typing import Any, Optional

import pdf_store
import vector_store as vs

EMBED_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
# Cosine distance threshold for connecting two tables (pgvector <=> ).
# Lower = stricter. ~0.35–0.45 works for table_summary chunks in practice.
DEFAULT_DISTANCE_THRESHOLD = float(os.environ.get("PDF_GROUP_DISTANCE", "0.42"))
TOP_K = int(os.environ.get("PDF_GROUP_TOP_K", "8"))


def build_table_summary_chunk(table: dict) -> str:
    parts = [
        table.get("title") or "",
        table.get("domain") or "",
        table.get("subject") or "",
        table.get("entity") or "",
        table.get("table_type") or "",
        table.get("geography") or "",
        table.get("time_period") or "",
        table.get("frequency") or "",
        table.get("unit") or "",
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
    key = (api_key or os.environ.get("OPENAI_API_KEY") or "").strip()
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


def index_tables(conn, job_id: str, tables: list[dict], api_key: Optional[str] = None) -> int:
    """Chunk + upsert embeddings for tables. Returns number of summary chunks written."""
    vs.ensure_semantic_embeddings_table(conn)
    summaries = [build_table_summary_chunk(t) for t in tables]
    vectors = embed_texts(summaries, api_key=api_key)
    n = 0
    for table, text, emb in zip(tables, summaries, vectors):
        if not text.strip():
            text = table.get("table_id") or table.get("id") or "untitled"
        vs.upsert_embedding(
            conn,
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
                    conn,
                    object_type="pdf_table",
                    object_id=table["id"],
                    chunk_kind=kind,
                    chunk_text=ctext,
                    embedding=cemb,
                    metadata={"job_id": job_id, "table_id": table.get("table_id")},
                    job_id=job_id,
                )
    return n


def _load_summary_embeddings(conn, job_id: str) -> dict[str, list[float]]:
    """object_id → embedding vector for table_summary chunks in this job."""
    try:
        from pgvector.psycopg2 import register_vector
        register_vector(conn)
    except Exception:
        pass
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT object_id::text, embedding::text
              FROM semantic_embeddings
             WHERE chunk_kind = 'table_summary'
               AND object_type = 'pdf_table'
               AND (job_id = %s OR metadata->>'job_id' = %s)
            """,
            (job_id, job_id),
        )
        rows = cur.fetchall()
    out = {}
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
                out[str(oid)] = [float(x) for x in s[1:-1].split(",") if x.strip()]
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
    for key in ("subject", "domain", "entity", "title"):
        vals = [str(m.get(key) or "").strip() for m in members]
        vals = [v for v in vals if v]
        if not vals:
            continue
        # Most common non-empty
        best = max(set(vals), key=vals.count)
        if best:
            return _clean_group_display_name(best)[:80]
    return f"Group {index + 1}"


# Merged multi-page tables append "(pages 1–2)" to the table title for
# provenance; that suffix must not carry into the group display name.
_PAGES_IN_TITLE_RE = re.compile(
    r"\s*\(\s*pages?\s+\d+(?:\s*[–—\-]\s*\d+)?\s*\)\s*$",
    re.IGNORECASE,
)


def _clean_group_display_name(name: str) -> str:
    cleaned = _PAGES_IN_TITLE_RE.sub("", name or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
    return cleaned or (name or "").strip()


# --- SDG India Index / indicator-table grouping ---------------------------
# When a job is clearly a set of per-goal indicator tables (e.g. titles like
# "TABLE 1.1: … INDICATORS OF SDG 1", columns "SDG 1 Index Score"), bucket by
# goal number instead of embedding similarity. Non-SDG jobs keep clustering.

_SDG_GOAL_RE = re.compile(r"\bSDG\s*(\d{1,2})\b", re.IGNORECASE)
_SDG_INDICATORS_RE = re.compile(
    r"INDICATORS?\s+OF\s+SDG\s*(\d{1,2})\b", re.IGNORECASE
)
_SDG_INDEX_RE = re.compile(r"\bSDG\s*(\d{1,2})\s*Index\b", re.IGNORECASE)
_TABLE_MAJOR_RE = re.compile(r"\bTABLE\s+(\d{1,2})\.\d+", re.IGNORECASE)
_SDA_TITLE_HINT_RE = re.compile(
    r"\b(SDG|INDICATOR|STATES?\s*/?\s*UTs?)\b", re.IGNORECASE
)


def _valid_sdg_goal(n: int) -> Optional[int]:
    return n if 1 <= n <= 17 else None


def detect_sdg_goal(table: dict) -> Optional[int]:
    """
    Extract SDG goal 1–17 from title / columns / classification when present.
    Returns None if the table does not look goal-tagged.
    """
    title = str(table.get("title") or "")
    subject = str(table.get("subject") or "")
    domain = str(table.get("domain") or "")
    col_names: list[str] = []
    for col in table.get("columns") or []:
        if isinstance(col, dict):
            col_names.append(str(col.get("name") or ""))
        else:
            col_names.append(str(col))
    cols_blob = " | ".join(col_names)

    m = _SDG_INDICATORS_RE.search(title)
    if m:
        return _valid_sdg_goal(int(m.group(1)))

    m = _SDG_INDEX_RE.search(title)
    if m:
        return _valid_sdg_goal(int(m.group(1)))

    m = _SDG_GOAL_RE.search(title)
    if m:
        return _valid_sdg_goal(int(m.group(1)))

    # SDA India style: TABLE 3.1 + States/UTs / indicator wording → goal 3
    m = _TABLE_MAJOR_RE.search(title)
    if m and _SDA_TITLE_HINT_RE.search(title):
        return _valid_sdg_goal(int(m.group(1)))

    m = _SDG_INDEX_RE.search(cols_blob)
    if m:
        return _valid_sdg_goal(int(m.group(1)))

    # Avoid weak "SDG" mentions in long column blobs that list many goals;
    # only accept a single clear Index Score column match (above) or metadata.
    for field in (subject, domain):
        m = _SDG_GOAL_RE.search(field)
        if m:
            return _valid_sdg_goal(int(m.group(1)))

    return None


def corpus_looks_like_sdg_indicator_tables(tables: list[dict]) -> bool:
    """
    True when enough tables carry a detectable SDG goal that SDG-wise
    buckets are safer than embedding clusters.
    """
    if len(tables) < 2:
        return False
    tagged_goals = [detect_sdg_goal(t) for t in tables]
    tagged = [g for g in tagged_goals if g is not None]
    if len(tagged) < 2:
        return False
    ratio = len(tagged) / len(tables)
    distinct = set(tagged)
    # Majority tagged, or several goals with a solid tagged share.
    if ratio >= 0.5:
        return True
    if len(distinct) >= 2 and ratio >= 0.35:
        return True
    return False


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


def _propose_sdg_groups(
    tables: list[dict],
    embeddings: dict[str, list[float]],
    threshold: float,
) -> list[dict]:
    """Bucket by SDG goal; leftover tables still use embedding clusters."""
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
        by_id = {t["id"]: t for t in leftovers}
        clusters = _cluster_by_distance(
            [t["id"] for t in leftovers],
            embeddings,
            threshold,
        )
        groups.extend(_groups_from_clusters(clusters, by_id, name_start_index=len(groups)))

    return groups


def propose_groups(
    conn,
    job_id: str,
    *,
    threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    api_key: Optional[str] = None,
    reindex: bool = False,
) -> dict[str, Any]:
    """
    Ensure embeddings exist, cluster, return grouping payload + method used.

    When the job looks like per-goal SDG indicator tables, groups are named
    SDG 1 / SDG 2 / … instead of embedding clusters.
    """
    tables = pdf_store.list_active_tables(conn, job_id)
    if not tables:
        return {
            "groups": [],
            "unmatched_tables": [],
            "method": "empty",
            "indexed": 0,
        }

    embeddings = _load_summary_embeddings(conn, job_id)
    missing = [t for t in tables if t["id"] not in embeddings]
    indexed = 0
    if reindex or missing:
        indexed = index_tables(conn, job_id, tables if reindex else missing, api_key=api_key)
        embeddings = _load_summary_embeddings(conn, job_id)

    method = "pgvector"
    if len(embeddings) < len(tables):
        # Fill gaps with pseudo vectors from summary text
        for t in tables:
            if t["id"] not in embeddings:
                embeddings[t["id"]] = _pseudo_embedding(
                    build_table_summary_chunk(t), vs.embedding_dim()
                )
        method = "hybrid"

    by_id = {t["id"]: t for t in tables}

    if corpus_looks_like_sdg_indicator_tables(tables):
        groups = _propose_sdg_groups(tables, embeddings, threshold)
        method = "sdg_goal"
    else:
        clusters = _cluster_by_distance(
            [t["id"] for t in tables],
            embeddings,
            threshold,
        )
        # Prefer multi-table clusters as named groups; leave true singletons unmatched
        # only when they didn't connect — still put each cluster as a group so
        # Automatic mode matches Excel (everything grouped, user can edit).
        groups = _groups_from_clusters(clusters, by_id)

    groups.sort(key=lambda g: (-len(g["tables"]), g["name"].lower()))
    if method == "sdg_goal":
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
        "indexed": indexed,
        "threshold": threshold,
    }


def apply_proposal_to_db(conn, job_id: str, proposal: dict) -> dict:
    """Persist proposal via pdf_store.save_grouping and return load_grouping shape."""
    groups_payload = [
        {"name": g["name"], "table_pks": g.get("table_pks") or [t["id"] for t in g.get("tables") or []]}
        for g in proposal.get("groups") or []
    ]
    pdf_store.save_grouping(conn, job_id=job_id, groups=groups_payload)
    loaded = pdf_store.load_grouping(conn, job_id)
    loaded["method"] = proposal.get("method")
    loaded["indexed"] = proposal.get("indexed", 0)
    loaded["threshold"] = proposal.get("threshold")
    return loaded
