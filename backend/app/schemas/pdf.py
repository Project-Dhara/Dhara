"""PDF review / grouping JSON bodies.

Keep types loose (``Any``, optional fields, ``extra="ignore"``) so existing
UI payloads continue to validate. Handlers still apply the same runtime checks.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TableIdsRequest(BaseModel):
    """Bodies that only need ``table_ids`` (delete / merge / zip)."""

    model_config = ConfigDict(extra="ignore")

    table_ids: Optional[List[Any]] = None


class AiSearchRequest(BaseModel):
    """POST .../tables/ai-search — UI also sends a ``tables`` hint list."""

    model_config = ConfigDict(extra="ignore")

    prompt: Optional[str] = None
    query: Optional[str] = None
    tables: Optional[List[Dict[str, Any]]] = None


class PersistApprovedRequest(BaseModel):
    """POST .../persist-approved — body may be omitted entirely by grouping UI."""

    model_config = ConfigDict(extra="ignore")

    tables: Optional[List[Dict[str, Any]]] = None
    approved_table_ids: Optional[List[Any]] = None


class GroupingProposeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reindex: bool = False


class GroupingSaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Required — same as previous handler check for a `groups` array.
    groups: List[Dict[str, Any]]


class ReviewTablePatch(BaseModel):
    """Free-form steward edits merged into job reviews (any keys allowed)."""

    model_config = ConfigDict(extra="allow")
