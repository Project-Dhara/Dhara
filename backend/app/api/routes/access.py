"""Versioned public access API for published catalogue datasets.

JWT-protected read endpoints shared with the MCP surface (same query helpers).
Tenant-scoped: callers only see datasets for their organisation.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import CurrentUser, require_user
from app.db.session import session_scope
from app.services.catalogue import query as catalogue_query

router = APIRouter(prefix="/api/v1", tags=["Access"])


def _with_session(fn):
    with session_scope() as session:
        return fn(session)


@router.get("", summary="Access API index")
async def access_index(user: CurrentUser = Depends(require_user)):
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
            "http": "/mcp",
            "stdio": "cd backend && python -m app.mcp",
            "auth": (
                "Open by default (published reads). "
                "Set MCP_HTTP_AUTH=jwt for login Bearer, or token + MCP_AUTH_TOKEN"
            ),
            "note": "HTTP MCP wraps the same query helpers as these REST routes.",
        },
        "organisation_id": str(user.organisation_id),
    }


@router.get("/datasets", summary="Search / list published datasets")
async def list_datasets(
    q: str | None = Query(None, description="Case-insensitive text search"),
    metadata_id: str | None = Query(None, description="Filter to one catalogue release"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(require_user),
):
    def _run():
        return _with_session(
            lambda session: catalogue_query.search_catalogue_datasets(
                session,
                q=q,
                metadata_id=metadata_id,
                limit=limit,
                offset=offset,
                organisation_id=user.organisation_id,
            )
        )

    return await asyncio.to_thread(_run)


@router.get("/datasets/{dataset_id}", summary="Get published dataset metadata")
async def get_dataset(dataset_id: str, user: CurrentUser = Depends(require_user)):
    def _run():
        return _with_session(
            lambda session: catalogue_query.get_catalogue_dataset(
                session, dataset_id, organisation_id=user.organisation_id
            )
        )

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
    user: CurrentUser = Depends(require_user),
):
    def _run():
        def _inner(session):
            ds = catalogue_query.get_catalogue_dataset(
                session, dataset_id, organisation_id=user.organisation_id
            )
            if not ds:
                return None
            return catalogue_query.query_dataset_rows(
                session,
                dataset_id,
                limit=limit,
                offset=offset,
                column=column,
                equals=equals,
                contains=contains,
                organisation_id=user.organisation_id,
            )

        return _with_session(_inner)

    result = await asyncio.to_thread(_run)
    if result is None:
        raise HTTPException(404, f"Dataset not found: {dataset_id}")
    return result
