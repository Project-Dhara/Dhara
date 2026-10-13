"""Read-only catalogue queries shared by REST and MCP surfaces.

Delegates to ``app.db.repositories.catalogue`` (SQLAlchemy Session).
"""
from __future__ import annotations

from app.db.repositories.catalogue import (  # noqa: F401
    get_catalogue_dataset,
    get_catalogue_group,
    list_catalogue_datasets,
    list_catalogue_groups,
    query_dataset_rows,
    search_catalogue_datasets,
)

__all__ = [
    "get_catalogue_dataset",
    "get_catalogue_group",
    "list_catalogue_datasets",
    "list_catalogue_groups",
    "query_dataset_rows",
    "search_catalogue_datasets",
]
