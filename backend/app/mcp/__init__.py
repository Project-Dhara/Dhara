"""DHARA Catalogue MCP server.

Exposes search_datasets, get_metadata, and get_table tools that call the same
helpers as GET /api/v1/datasets*.

Transports
----------
* **stdio** (local agents)::

      cd backend && python -m app.mcp

* **Streamable HTTP** (deployed URL ``/mcp``): mounted from ``app.main`` —
  see ``app.mcp.http_asgi``. Same tools; auth via Bearer JWT by default.
"""
from __future__ import annotations

import json
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Optional
from uuid import UUID

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(_BACKEND_ROOT / ".env")

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.db.session import session_scope
from app.services.catalogue import query as catalogue_query

# Set by Streamable HTTP auth when JWT is validated.
mcp_organisation_id: ContextVar[Optional[UUID]] = ContextVar(
    "mcp_organisation_id", default=None
)

mcp = FastMCP(
    "DHARA Catalogue",
    instructions=(
        "Query published DHARA catalogue datasets. "
        "Use search_datasets to discover tables, get_metadata for one dataset, "
        "and get_table to page through row data."
    ),
    host="0.0.0.0",
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _with_session(fn):
    with session_scope() as session:
        return fn(session)


def _org_id() -> Optional[UUID]:
    return mcp_organisation_id.get()


def _json(payload) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False, indent=2)


@mcp.tool()
def search_datasets(
    q: str = "",
    metadata_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Search published catalogue datasets by text and/or metadata release id.

    Args:
        q: Optional case-insensitive search text (title, geo, source, tags).
        metadata_id: Optional metadata group / release id to filter to.
        limit: Max datasets to return (1–500).
        offset: Pagination offset.
    """
    org = _org_id()
    result = _with_session(
        lambda session: catalogue_query.search_catalogue_datasets(
            session,
            q=q or None,
            metadata_id=metadata_id or None,
            limit=limit,
            offset=offset,
            organisation_id=org,
        )
    )
    return _json(result)


@mcp.tool()
def get_metadata(dataset_id: str) -> str:
    """Get metadata for one published dataset.

    Args:
        dataset_id: Catalogue dataset id (same as REST /api/v1/datasets/{id}).
    """
    org = _org_id()
    dataset = _with_session(
        lambda session: catalogue_query.get_catalogue_dataset(
            session, dataset_id, organisation_id=org
        )
    )
    if not dataset:
        return _json({"error": "not_found", "dataset_id": dataset_id})
    return _json({"dataset": dataset})


@mcp.tool()
def get_table(
    dataset_id: str,
    limit: int = 100,
    offset: int = 0,
    column: str = "",
    equals: str = "",
    contains: str = "",
) -> str:
    """Fetch paginated rows for a published dataset, with optional column filter.

    Args:
        dataset_id: Catalogue dataset id.
        limit: Page size (1–500).
        offset: Pagination offset.
        column: Optional row_data key to filter on.
        equals: Exact match on column (requires column).
        contains: Substring match on column (requires column; ignored if equals set).
    """
    org = _org_id()
    try:
        payload = _with_session(
            lambda session: catalogue_query.query_dataset_rows(
                session,
                dataset_id,
                limit=limit,
                offset=offset,
                column=column or None,
                equals=equals if equals != "" else None,
                contains=contains if contains != "" and equals == "" else None,
                organisation_id=org,
            )
        )
    except ValueError as exc:
        return _json({"error": "bad_request", "message": str(exc)})
    if payload is None:
        return _json({"error": "not_found", "dataset_id": dataset_id})
    return _json(payload)


def main():
    mcp.run(transport="stdio")
