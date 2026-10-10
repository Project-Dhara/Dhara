"""Storage interfaces (local + no-op object store)."""
from __future__ import annotations

from pathlib import Path

from app.core.config import clear_settings_cache
from app.storage.files import NoOpObjectStore
from app.storage.local import LocalFileStore
from app.storage.object_store import get_object_store


def test_noop_object_store_returns_none(monkeypatch):
    monkeypatch.setenv("ENABLE_GCS", "false")
    clear_settings_cache()
    store = NoOpObjectStore()
    assert store.put_bytes("k", b"data") is None
    assert store.enabled() is False


def test_get_object_store_disabled_by_default(monkeypatch):
    monkeypatch.setenv("ENABLE_GCS", "false")
    clear_settings_cache()
    store = get_object_store()
    assert store.put_bytes("datasets/x.xlsx", b"x") is None


def test_local_file_store_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_LOCAL_PATH", str(tmp_path / "blobs"))
    clear_settings_cache()
    store = LocalFileStore()
    uri = store.put_bytes("datasets/ds-1.xlsx", b"excel-bytes")
    assert uri and uri.startswith("file://")
    path = store.resolve_path("datasets/ds-1.xlsx")
    assert path.read_bytes() == b"excel-bytes"
