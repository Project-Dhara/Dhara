"""Versioned public access API for published catalogue datasets.

JWT-protected read endpoints shared with the MCP surface (same query helpers).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from catalogue import catalogue as _cat
from catalogue import query as catalogue_query
from core.deps import require_user

router = APIRouter(prefix="/api/v1", tags=["Access"])


def _with_conn(fn):
    conn = _cat.get_connection()
    try:
        _cat.init_schema(conn)
        return fn(conn)
    finally:
        conn.close()


@router.get("", summary="Access API index")
async def access_index(user_email: str = Depends(require_user)):
    """Describe the catalogue access surface (REST + MCP tools)."""
    return {
        "name": "DHARA Catalogue Access API",
        "version": "v1",
        "auth": "Bearer JWT (same as Console login)",
        "endpoints": {
            "list_datasets": "GET /api/v1/datasets",
            "get_dataset": "GET /api/v1/datasets/{dataset_id}",
            "query_rows": "GET /api/v1/datasets/{dataset_id}/rows",
        },
        "mcp_tools": ["search_datasets", "get_metadata", "get_table"],
        "mcp": {
            "stdio": "cd backend && python -m mcp_server",
            "note": "MCP wraps the same query helpers as these REST routes.",
        },
    }


@router.get("/datasets", summary="Search / list published datasets")
async def list_datasets(
    q: str | None = Query(None, description="Case-insensitive text search"),
    metadata_id: str | None = Query(None, description="Filter to one catalogue release"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_email: str = Depends(require_user),
):
    def _run():
        return _with_conn(
            lambda conn: catalogue_query.search_catalogue_datasets(
                conn,
                q=q,
                metadata_id=metadata_id,
                limit=limit,
                offset=offset,
            )
        )

    return await asyncio.to_thread(_run)


@router.get("/datasets/{dataset_id}", summary="Get published dataset metadata")
async def get_dataset(dataset_id: str, user_email: str = Depends(require_user)):
    def _run():
        return _with_conn(lambda conn: catalogue_query.get_catalogue_dataset(conn, dataset_id))

    dataset = await asyncio.to_thread(_run)
    if not dataset:
        raise HTTPException(404, f"Dataset not found: {dataset_id}")
    return {"dataset": dataset}


@router.get("/datasets/{dataset_id}/rows", summary="Query published dataset rows")
async def get_dataset_rows(
    dataset_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    column: str | None = Query(None, description="row_data key to filter on"),
    equals: str | None = Query(None, description="Exact match on column"),
    contains: str | None = Query(None, description="Substring match on column (ILIKE)"),
    user_email: str = Depends(require_user),
):
    def _run():
        return _with_conn(
            lambda conn: catalogue_query.query_dataset_rows(
                conn,
                dataset_id,
                limit=limit,
                offset=offset,
                column=column,
                equals=equals,
                contains=contains,
            )
        )

    try:
        payload = await asyncio.to_thread(_run)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if payload is None:
        raise HTTPException(404, f"Dataset not found: {dataset_id}")
    return payload
