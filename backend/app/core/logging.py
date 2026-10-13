"""Logging setup with secret redaction."""
from __future__ import annotations

import logging
import re
from typing import Iterable

_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)(\S+)"),
    re.compile(r"(?i)(x-llm-api-key\s*[:=]\s*)(\S+)"),
    re.compile(r'(?i)(["\']?api_key["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])'),
    re.compile(r'(?i)(["\']?password["\']?\s*[:=]\s*["\'])([^"\']+)(["\'])'),
    re.compile(
        r"(?i)(postgres(?:ql)?(?:\+psycopg2)?://[^:]+:)([^@]+)(@)"
    ),
    re.compile(r"(?i)(gAAAA[A-Za-z0-9_\-]{20,})"),
)


def redact_secrets(text: str) -> str:
    """Replace credential-like substrings with a fixed placeholder."""
    if not text:
        return text
    out = text
    for pat in _REDACT_PATTERNS:
        if pat.groups >= 3:
            out = pat.sub(r"\1***\3", out)
        elif pat.groups == 2:
            out = pat.sub(r"\1***", out)
        elif pat.groups == 1:
            out = pat.sub("***", out)
        else:
            out = pat.sub("***", out)
    return out


class RedactingFilter(logging.Filter):
    """Logging filter that redacts secrets from the formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = redact_secrets(msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a redacting filter to the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(f, RedactingFilter) for f in root.filters):
        root.addFilter(RedactingFilter())
    for handler in root.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())


def ensure_handlers_redact(loggers: Iterable[str] | None = None) -> None:
    configure_logging()
    for name in loggers or ():
        logging.getLogger(name).addFilter(RedactingFilter())
