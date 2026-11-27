"""Legacy Hindi font → Unicode Devanagari converters (Kruti Dev 010, Chanakya)."""

from __future__ import annotations

from .chanakya import chanakya_to_unicode
from .krutidev010 import krutidev_to_unicode

__all__ = ["krutidev_to_unicode", "chanakya_to_unicode"]
