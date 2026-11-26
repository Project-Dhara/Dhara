"""Classify OpenAI-compatible / Ollama API errors for metadata autofill retries.

Match lists live in one place. Message text differs across servers, so keep
variants short and log the full text when nothing matches.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Fail fast — do not retry without schema.
_CONTEXT_LENGTH_MARKERS = (
    "context length",
    "maximum context",
    "context window",
    "too many tokens",
    "prompt too long",
    "prompt is too long",
    "exceeds the context",
    "exceed context",
    "max context",
    "n_ctx",
    "num_ctx",
    # Broad but common; combined with "token"/"length" checks in helper
    "too long",
)


def _error_text(exc_or_msg: Any) -> str:
    if exc_or_msg is None:
        return ""
    if isinstance(exc_or_msg, BaseException):
        parts = [str(exc_or_msg)]
        body = getattr(exc_or_msg, "body", None)
        if body is not None:
            parts.append(str(body))
        msg = getattr(exc_or_msg, "message", None)
        if msg is not None and str(msg) not in parts[0]:
            parts.append(str(msg))
        return " ".join(parts)
    return str(exc_or_msg)


def is_format_unsupported_error(exc_or_msg: Any) -> bool:
    """True when the server rejected response_format / json_schema / similar."""
    text = _error_text(exc_or_msg).lower()
    if not text:
        return False
    # Require an explicit format-ish marker; "unsupported" alone is too broad
    # unless paired with format vocabulary.
    has_format_vocab = any(
        m in text
        for m in ("response_format", "json_schema", "json_object", "response format")
    )
    if has_format_vocab:
        return True
    if "unsupported" in text and any(
        m in text for m in ("parameter", "argument", "option", "format", "schema")
    ):
        return True
    if "unknown parameter" in text or "invalid parameter" in text:
        return True
    return False


def is_context_length_error(exc_or_msg: Any) -> bool:
    """True when the prompt/context exceeded the model's window."""
    text = _error_text(exc_or_msg).lower()
    if not text:
        return False
    for marker in _CONTEXT_LENGTH_MARKERS:
        if marker in text:
            # "too long" alone can be ambiguous; prefer when token/context nearby
            if marker == "too long":
                if any(
                    w in text
                    for w in ("token", "context", "prompt", "input", "message", "request")
                ):
                    return True
                continue
            return True
    # OpenAI: "This model's maximum context length is X tokens"
    if "maximum" in text and "token" in text and (
        "context" in text or "length" in text
    ):
        return True
    return False


CONTEXT_LENGTH_USER_MESSAGE = (
    "Context length exceeded — shrink the prompt or raise Ollama num_ctx / "
    "OLLAMA_CONTEXT_LENGTH. The /v1 API cannot set context size per request."
)


def classify_llm_api_error(exc_or_msg: Any) -> str:
    """Return 'context', 'format', or 'other'. Logs full text when unmatched."""
    if is_context_length_error(exc_or_msg):
        return "context"
    if is_format_unsupported_error(exc_or_msg):
        return "format"
    logger.warning(
        "LLM API error did not match format/context classifiers: %s",
        _error_text(exc_or_msg),
    )
    return "other"


__all__ = [
    "CONTEXT_LENGTH_USER_MESSAGE",
    "classify_llm_api_error",
    "is_context_length_error",
    "is_format_unsupported_error",
]
