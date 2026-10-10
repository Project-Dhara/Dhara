"""Local filesystem object storage (dev / air-gapped)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import quote

from app.core.config import get_settings


class LocalFileStore:
    """Write blobs under ``STORAGE_LOCAL_PATH``; return ``file://`` URIs."""

    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self._root = Path(root or settings.storage_local_path).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> Optional[str]:
        safe = key.lstrip("/").replace("..", "_")
        path = self._root / safe
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"file://{quote(str(path))}"

    def enabled(self) -> bool:
        return True

    def resolve_path(self, key: str) -> Path:
        safe = key.lstrip("/").replace("..", "_")
        return self._root / safe
