"""KYDS (Know Your Dataset) request/response contracts."""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class KydsSaveRequest(BaseModel):
    """Body for POST /api/kyds and PATCH /api/kyds/{id}."""

    model_config = ConfigDict(extra="ignore")

    responses: Dict[str, Any] = Field(
        ...,
        description="Survey answers keyed by question id",
    )


class KydsSaveResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    status: str


class KydsEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    responses: Dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class KydsMineResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entry: Optional[KydsEntry] = None


class KydsPatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entry: KydsEntry
    status: str
