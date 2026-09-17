"""DHARA Catalogue MCP server (stdio).

Exposes search_datasets, get_metadata, and get_table tools that call the same
helpers as GET /api/v1/datasets*.

Run from the backend directory::

    python -m mcp_server

Point an MCP client (Cursor, Claude Desktop, etc.) at that command with
cwd = backend/ and DATABASE_URL available (e.g. via backend/.env).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(_BACKEND_ROOT / ".env")

from mcp.server.fastmcp import FastMCP

from catalogue import catalogue as _cat
from catalogue import query as catalogue_query

mcp = FastMCP(
    "DHARA Catalogue",
    instructions=(
        "Query published DHARA catalogue datasets. "
        "Use search_datasets to discover tables, get_metadata for one dataset, "
        "and get_table to page through row data."
    ),
)


def _with_conn(fn):
    conn = _cat.get_connection()
    try:
        _cat.init_schema(conn)
        return fn(conn)
    finally:
        conn.close()


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
    result = _with_conn(
        lambda conn: catalogue_query.search_catalogue_datasets(
            conn,
            q=q or None,
            metadata_id=metadata_id or None,
            limit=limit,
            offset=offset,
        )
    )
    return _json(result)


@mcp.tool()
def get_metadata(dataset_id: str) -> str:
    """Get metadata for one published dataset.

    Args:
        dataset_id: Catalogue dataset id (same as REST /api/v1/datasets/{id}).
    """
    dataset = _with_conn(lambda conn: catalogue_query.get_catalogue_dataset(conn, dataset_id))
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
    try:
        payload = _with_conn(
            lambda conn: catalogue_query.query_dataset_rows(
                conn,
                dataset_id,
                limit=limit,
                offset=offset,
                column=column or None,
                equals=equals if equals != "" else None,
                contains=contains if contains != "" and equals == "" else None,
            )
        )
    except ValueError as exc:
        return _json({"error": "bad_request", "message": str(exc)})
    if payload is None:
        return _json({"error": "not_found", "dataset_id": dataset_id})
    return _json(payload)


def main():
    mcp.run(transport="stdio")
