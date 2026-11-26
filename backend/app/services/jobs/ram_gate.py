"""Gate PDF uploads when the host has too little free RAM."""
from __future__ import annotations

import os

from app.core.exceptions import AppError
from app.services.llm_prompts import _available_ram_mb

_DEFAULT_MIN_MB = 1200
_INSUFFICIENT_RAM_MESSAGE = (
    "Your PC does not have enough free memory to process this file right now "
    "(need about 1.2 GB free). Close other apps—especially browsers and local "
    "AI—and try again."
)


def _min_available_ram_mb() -> int:
    raw = (os.environ.get("DHARA_MIN_AVAILABLE_RAM_MB") or "").strip()
    if not raw:
        return _DEFAULT_MIN_MB
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MIN_MB


def ensure_enough_ram_for_pdf() -> None:
    """Raise ``AppError`` (503) when available RAM is below the PDF threshold."""
    threshold = _min_available_ram_mb()
    avail = _available_ram_mb()
    if avail is None:
        return
    if avail < threshold:
        raise AppError(_INSUFFICIENT_RAM_MESSAGE, status_code=503)