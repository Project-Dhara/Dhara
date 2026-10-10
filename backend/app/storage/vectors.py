"""Pgvector-backed semantic retrieval (Postgres-only ancillary index)."""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from app.core.config import get_settings


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
    """Delegates to ``core.vector_store`` (psycopg2 + pgvector)."""

    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim or get_settings().embedding_dim

    def ensure_schema(self, conn, *, dim: int | None = None) -> None:
        from core import vector_store as vs

        vs.ensure_semantic_embeddings_table(conn, dim=dim or self._dim)

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
        from core import vector_store as vs

        return vs.upsert_embedding(
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
        from core import vector_store as vs

        return vs.similarity_search(
            conn,
            query_embedding,
            limit=limit,
            object_type=object_type,
            chunk_kind=chunk_kind,
            user_email=user_email,
        )

    def extension_ready(self, conn) -> bool:
        from core import vector_store as vs

        return vs.vector_extension_ready(conn)


def get_vector_store() -> PgVectorStore:
    return PgVectorStore()
