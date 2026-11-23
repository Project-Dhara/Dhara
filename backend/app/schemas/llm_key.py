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
        description="Provider id (e.g. openai, anthropic, self-hosted)",
        examples=["openai"],
    )
    base_url: Optional[str] = Field(
        None,
        description="OpenAI-compatible base URL for self-hosted (e.g. Ollama /v1)",
        examples=["http://host.docker.internal:11434/v1"],
    )
    model: Optional[str] = Field(
        None,
        description="Chat model id for self-hosted / override",
        examples=["qwen2.5:1.5b-instruct"],
    )


class LlmKeyStatusResponse(BaseModel):
    """GET /api/llm-key and save/clear responses."""

    model_config = ConfigDict(extra="ignore")

    configured: bool
    provider: Optional[str] = None
    updated_at: Optional[Any] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    crypto_error: bool = False
    status: Optional[str] = None
