"""Shared OpenAI-compatible client factory (cloud or self-hosted / Ollama)."""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from app.services.llm_prompts import OPENAI_MODEL

# Default small CPU model for desktop / Ollama self-hosted (8 GB profile).
DEFAULT_SELF_HOSTED_MODEL = os.environ.get(
    "DHARA_SELF_HOSTED_MODEL", "gemma3:1b"
).strip() or "gemma3:1b"


@dataclass(frozen=True)
class LlmCallContext:
    api_key: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


_llm_ctx: ContextVar[Optional[LlmCallContext]] = ContextVar("dhara_llm_ctx", default=None)


@contextmanager
def llm_credentials_context(
    api_key: Optional[str] = None,
    *,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Iterator[LlmCallContext]:
    """Bind credentials for nested OpenAI calls (PDF worker, extract, etc.)."""
    ctx = LlmCallContext(
        api_key=(api_key or "").strip() or None,
        provider=(provider or "").strip() or None,
        base_url=(base_url or "").strip() or None,
        model=(model or "").strip() or None,
    )
    token = _llm_ctx.set(ctx)
    try:
        yield ctx
    finally:
        _llm_ctx.reset(token)


def env_llm_base_url() -> Optional[str]:
    raw = (os.environ.get("LLM_BASE_URL") or "").strip()
    return raw or None


def env_llm_model() -> Optional[str]:
    raw = (os.environ.get("LLM_MODEL") or "").strip()
    return raw or None


def _active_ctx() -> Optional[LlmCallContext]:
    return _llm_ctx.get()


def make_openai_client(
    api_key: Optional[str] = None,
    *,
    base_url: Optional[str] = None,
    timeout: float | None = None,
):
    """Build an OpenAI SDK client; ``base_url`` enables Ollama / local /v1 servers."""
    from openai import OpenAI

    ctx = _active_ctx()
    key = (api_key or (ctx.api_key if ctx else None) or "").strip() or "ollama"
    url = (
        (base_url or "").strip()
        or (ctx.base_url if ctx else None)
        or env_llm_base_url()
        or ""
    ).strip()
    kwargs: dict[str, Any] = {"api_key": key}
    if url:
        kwargs["base_url"] = url.rstrip("/")
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def resolve_chat_model(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Pick chat model id: stored/env override, else self-hosted default, else cloud default."""
    ctx = _active_ctx()
    explicit = (
        (model or "").strip()
        or (ctx.model if ctx else None)
        or env_llm_model()
        or ""
    ).strip()
    if explicit:
        return explicit
    prov = (
        (provider or "").strip()
        or (ctx.provider if ctx else None)
        or ""
    ).strip().lower()
    url = (
        (base_url or "").strip()
        or (ctx.base_url if ctx else None)
        or env_llm_base_url()
        or ""
    ).strip()
    if prov in ("self-hosted", "ollama") or url:
        return DEFAULT_SELF_HOSTED_MODEL
    return OPENAI_MODEL
