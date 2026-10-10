"""Pgvector-backed semantic retrieval (Postgres-only ancillary index).

PostgreSQL remains the source of truth for metadata, classifications,
mappings, and provenance. This module stores/searches embeddings so
DHARA can find semantically similar objects quickly.

Does not decide relationships — that stays with LLM reasoning + human review.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Optional, Protocol, runtime_checkable

import psycopg2.extras

from app.core.config import get_settings

# Default matches OpenAI text-embedding-3-small (also used by nco_matching).
DEFAULT_EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1536"))


def embedding_dim() -> int:
    try:
        return int(get_settings().embedding_dim)
    except Exception:
        return DEFAULT_EMBEDDING_DIM


def ensure_vector_extension(conn) -> None:
    """Enable pgvector on the current database (safe to call repeatedly)."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()


def ensure_semantic_embeddings_table(conn, dim: Optional[int] = None) -> None:
    """
    Create the ancillary embeddings table + HNSW cosine index.

    Columns mirror pipeline Stage 6: chunk text + vector, keyed to an
    authoritative object (dataset / table / column / concept / …) by id.
    """
    dim = dim or embedding_dim()
    ensure_vector_extension(conn)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS semantic_embeddings (
                id            UUID PRIMARY KEY,
                object_type   TEXT NOT NULL,
                object_id     TEXT NOT NULL,
                chunk_kind    TEXT NOT NULL,
                chunk_text    TEXT NOT NULL,
                embedding     vector({dim}),
                metadata      JSONB DEFAULT '{{}}',
                user_email    TEXT,
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                updated_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (object_type, object_id, chunk_kind)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_hnsw
                ON semantic_embeddings
                USING hnsw (embedding vector_cosine_ops)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_object
                ON semantic_embeddings (object_type, object_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_kind
                ON semantic_embeddings (chunk_kind)
            """
        )
        cur.execute(
            "ALTER TABLE semantic_embeddings ADD COLUMN IF NOT EXISTS job_id TEXT"
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_semantic_embeddings_job
                ON semantic_embeddings (job_id)
            """
        )
    conn.commit()


def _register_vector(conn) -> None:
    try:
        from pgvector.psycopg2 import register_vector

        register_vector(conn)
    except Exception:
        # Fallback: pass embeddings as literal strings '[…,'…']'
        pass


def upsert_embedding(
    conn,
    *,
    object_type: str,
    object_id: str,
    chunk_kind: str,
    chunk_text: str,
    embedding: list[float],
    metadata: Optional[dict[str, Any]] = None,
    user_email: Optional[str] = None,
    job_id: Optional[str] = None,
) -> str:
    """Insert or replace one semantic chunk embedding. Returns row id."""
    _register_vector(conn)
    row_id = str(uuid.uuid4())
    meta = psycopg2.extras.Json(metadata or {})
    jid = job_id or (metadata or {}).get("job_id")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO semantic_embeddings (
                id, object_type, object_id, chunk_kind, chunk_text,
                embedding, metadata, user_email, job_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (object_type, object_id, chunk_kind) DO UPDATE SET
                chunk_text  = EXCLUDED.chunk_text,
                embedding   = EXCLUDED.embedding,
                metadata    = EXCLUDED.metadata,
                user_email  = COALESCE(EXCLUDED.user_email, semantic_embeddings.user_email),
                job_id      = COALESCE(EXCLUDED.job_id, semantic_embeddings.job_id),
                updated_at  = NOW()
            RETURNING id::text
            """,
            (
                row_id,
                object_type,
                object_id,
                chunk_kind,
                chunk_text,
                embedding,
                meta,
                user_email,
                jid,
            ),
        )
        returned = cur.fetchone()[0]
    conn.commit()
    return returned


def similarity_search(
    conn,
    query_embedding: list[float],
    *,
    limit: int = 10,
    object_type: Optional[str] = None,
    chunk_kind: Optional[str] = None,
    user_email: Optional[str] = None,
) -> list[dict]:
    """
    Nearest-neighbour search by cosine distance (`<=>`).

    Returns dicts with object keys, chunk_text, metadata, and distance
    (lower = more similar). Does not decide relationships — retrieval only.
    """
    _register_vector(conn)
    clauses = ["embedding IS NOT NULL"]
    params: list[Any] = []
    if object_type:
        clauses.append("object_type = %s")
        params.append(object_type)
    if chunk_kind:
        clauses.append("chunk_kind = %s")
        params.append(chunk_kind)
    if user_email:
        clauses.append("(user_email IS NULL OR user_email = %s)")
        params.append(user_email)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT
            id::text AS id,
            object_type,
            object_id,
            chunk_kind,
            chunk_text,
            metadata,
            user_email,
            (embedding <=> %s::vector) AS distance
        FROM semantic_embeddings
        WHERE {where}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, [query_embedding] + params + [query_embedding, limit])
        return [dict(r) for r in cur.fetchall()]


def vector_extension_ready(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        return bool(cur.fetchone()[0])


@runtime_checkable
class VectorStore(Protocol):
    """Embedding upsert + similarity search against ``semantic_embeddings``."""

    def ensure_schema(self, conn, *, dim: int | None = None) -> None: ...

    def upsert_embedding(
        self,
        conn,
        *,
        object_type: str,
        object_id: str,
        chunk_kind: str,
        chunk_text: str,
        embedding: list[float],
        metadata: Optional[dict[str, Any]] = None,
        user_email: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> str: ...

    def similarity_search(
        self,
        conn,
        query_embedding: list[float],
        *,
        limit: int = 10,
        object_type: Optional[str] = None,
        chunk_kind: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> list[dict]: ...

    def extension_ready(self, conn) -> bool: ...


class PgVectorStore:
    """Object-oriented facade over the module-level helpers above."""

    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim or embedding_dim()

    def ensure_schema(self, conn, *, dim: int | None = None) -> None:
        ensure_semantic_embeddings_table(conn, dim=dim or self._dim)

    def upsert_embedding(
        self,
        conn,
        *,
        object_type: str,
        object_id: str,
        chunk_kind: str,
        chunk_text: str,
        embedding: list[float],
        metadata: Optional[dict[str, Any]] = None,
        user_email: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> str:
        return upsert_embedding(
            conn,
            object_type=object_type,
            object_id=object_id,
            chunk_kind=chunk_kind,
            chunk_text=chunk_text,
            embedding=embedding,
            metadata=metadata,
            user_email=user_email,
            job_id=job_id,
        )

    def similarity_search(
        self,
        conn,
        query_embedding: list[float],
        *,
        limit: int = 10,
        object_type: Optional[str] = None,
        chunk_kind: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> list[dict]:
        return similarity_search(
            conn,
            query_embedding,
            limit=limit,
            object_type=object_type,
            chunk_kind=chunk_kind,
            user_email=user_email,
        )

    def extension_ready(self, conn) -> bool:
        return vector_extension_ready(conn)


def get_vector_store() -> PgVectorStore:
    return PgVectorStore()
