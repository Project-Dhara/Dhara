"""Pgvector-backed semantic retrieval (SQLAlchemy Session).

PostgreSQL remains the source of truth for metadata, classifications,
mappings, and provenance. This module stores/searches embeddings so
DHARA can find semantically similar objects quickly.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Optional, Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings

DEFAULT_EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1536"))


def embedding_dim() -> int:
    try:
        return int(get_settings().embedding_dim)
    except Exception:
        return DEFAULT_EMBEDDING_DIM


def ensure_vector_extension(session: Session) -> None:
    """No-op when Alembic owns schema (default)."""
    if get_settings().disable_request_time_ddl:
        return
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    session.flush()


def ensure_semantic_embeddings_table(
    session: Session, dim: Optional[int] = None
) -> None:
    """No-op when Alembic owns schema (default)."""
    if get_settings().disable_request_time_ddl:
        return
    dim = dim or embedding_dim()
    ensure_vector_extension(session)
    session.execute(
        text(
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
    )
    session.flush()


def _vec_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def upsert_embedding(
    session: Session,
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
    row_id = str(uuid.uuid4())
    meta = metadata or {}
    jid = job_id or meta.get("job_id")
    import json

    returned = session.execute(
        text(
            """
            INSERT INTO semantic_embeddings (
                id, object_type, object_id, chunk_kind, chunk_text,
                embedding, metadata, user_email, job_id
            )
            VALUES (
                CAST(:id AS uuid), :object_type, :object_id, :chunk_kind, :chunk_text,
                CAST(:embedding AS vector), CAST(:metadata AS jsonb),
                :user_email, :job_id
            )
            ON CONFLICT (object_type, object_id, chunk_kind) DO UPDATE SET
                chunk_text  = EXCLUDED.chunk_text,
                embedding   = EXCLUDED.embedding,
                metadata    = EXCLUDED.metadata,
                user_email  = COALESCE(EXCLUDED.user_email, semantic_embeddings.user_email),
                job_id      = COALESCE(EXCLUDED.job_id, semantic_embeddings.job_id),
                updated_at  = NOW()
            RETURNING id::text
            """
        ),
        {
            "id": row_id,
            "object_type": object_type,
            "object_id": object_id,
            "chunk_kind": chunk_kind,
            "chunk_text": chunk_text,
            "embedding": _vec_literal(embedding),
            "metadata": json.dumps(meta),
            "user_email": user_email,
            "job_id": jid,
        },
    ).scalar_one()
    session.flush()
    return str(returned)


def similarity_search(
    session: Session,
    query_embedding: list[float],
    *,
    limit: int = 10,
    object_type: Optional[str] = None,
    chunk_kind: Optional[str] = None,
    user_email: Optional[str] = None,
) -> list[dict]:
    clauses = ["embedding IS NOT NULL"]
    params: dict[str, Any] = {
        "q": _vec_literal(query_embedding),
        "limit": limit,
    }
    if object_type:
        clauses.append("object_type = :object_type")
        params["object_type"] = object_type
    if chunk_kind:
        clauses.append("chunk_kind = :chunk_kind")
        params["chunk_kind"] = chunk_kind
    if user_email:
        clauses.append("(user_email IS NULL OR user_email = :user_email)")
        params["user_email"] = user_email
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
            (embedding <=> CAST(:q AS vector)) AS distance
        FROM semantic_embeddings
        WHERE {where}
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :limit
    """
    rows = session.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def vector_extension_ready(session: Session) -> bool:
    return bool(
        session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
        ).scalar_one()
    )


@runtime_checkable
class VectorStore(Protocol):
    def ensure_schema(self, session: Session, *, dim: int | None = None) -> None: ...

    def upsert_embedding(
        self,
        session: Session,
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
        session: Session,
        query_embedding: list[float],
        *,
        limit: int = 10,
        object_type: Optional[str] = None,
        chunk_kind: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> list[dict]: ...

    def extension_ready(self, session: Session) -> bool: ...


class PgVectorStore:
    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim or embedding_dim()

    def ensure_schema(self, session: Session, *, dim: int | None = None) -> None:
        ensure_semantic_embeddings_table(session, dim=dim or self._dim)

    def upsert_embedding(self, session: Session, **kwargs) -> str:
        return upsert_embedding(session, **kwargs)

    def similarity_search(self, session: Session, query_embedding, **kwargs) -> list[dict]:
        return similarity_search(session, query_embedding, **kwargs)

    def extension_ready(self, session: Session) -> bool:
        return vector_extension_ready(session)


def get_vector_store() -> PgVectorStore:
    return PgVectorStore()
