"""LLM credential settings contracts."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class LlmKeySaveRequest(BaseModel):
    """Body for POST /api/llm-key. Empty ``api_key`` clears the stored credential."""

    model_config = ConfigDict(extra="ignore")

    api_key: str = Field(
        "",
        description="Provider API key; omit or empty string to clear",
    )
    provider: Optional[str] = Field(
        None,
        description="Provider id (e.g. openai, anthropic)",
        examples=["openai"],
    )


class LlmKeyStatusResponse(BaseModel):
    """GET /api/llm-key and save/clear responses."""

    model_config = ConfigDict(extra="ignore")

    configured: bool
    provider: Optional[str] = None
    updated_at: Optional[Any] = None
    api_key: Optional[str] = None
    crypto_error: bool = False
    status: Optional[str] = None
