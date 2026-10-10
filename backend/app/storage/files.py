"""File / object storage abstractions for catalogue exports and uploads."""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class ObjectStore(Protocol):
    """Store opaque blobs; return a durable URL when cloud-backed, else None."""

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> Optional[str]:
        """Persist ``key`` and return ``gs://…`` URL, or None if storage is disabled."""

    def enabled(self) -> bool:
        """True when uploads are active (e.g. GCS configured)."""


class NoOpObjectStore:
    """Default when object storage is off — callers still write Postgres rows."""

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> Optional[str]:
        return None

    def enabled(self) -> bool:
        return False
