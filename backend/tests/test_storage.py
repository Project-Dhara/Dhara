"""Storage interfaces (local + no-op object store)."""
from __future__ import annotations

from pathlib import Path

from app.core.config import clear_settings_cache
from app.storage.files import NoOpObjectStore
from app.storage.local import LocalFileStore
from app.storage.object_store import get_object_store
from app.storage import upload_archive


def test_noop_object_store_returns_none(monkeypatch):
    monkeypatch.setenv("ENABLE_GCS", "false")
    clear_settings_cache()
    store = NoOpObjectStore()
    assert store.put_bytes("k", b"data") is None
    assert store.enabled() is False


def test_get_object_store_defaults_to_local(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_GCS", "false")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("STORAGE_LOCAL_PATH", str(tmp_path / "blobs"))
    clear_settings_cache()
    store = get_object_store()
    assert isinstance(store, LocalFileStore)
    uri = store.put_bytes("datasets/x.xlsx", b"x")
    assert uri and uri.startswith("file://")


def test_get_object_store_gcs_requires_bucket(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("GCS_BUCKET_NAME", "")
    monkeypatch.setenv("ENABLE_GCS", "true")
    clear_settings_cache()
    try:
        get_object_store()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "GCS_BUCKET_NAME" in str(exc)


def test_local_file_store_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_LOCAL_PATH", str(tmp_path / "blobs"))
    clear_settings_cache()
    store = LocalFileStore()
    uri = store.put_bytes("datasets/ds-1.xlsx", b"excel-bytes")
    assert uri and uri.startswith("file://")
    path = store.resolve_path("datasets/ds-1.xlsx")
    assert path.read_bytes() == b"excel-bytes"


def test_upload_archive_keeps_original_name_and_suffixes(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_ARCHIVE_PATH", str(tmp_path))
    first = upload_archive.archive_upload_bytes("report.pdf", b"one")
    second = upload_archive.archive_upload_bytes("../evil/report.pdf", b"two")
    third = upload_archive.archive_upload_bytes("report.pdf", b"three")
    assert first is not None and first.name == "report.pdf"
    assert first.parent.name == "pdf_uploads"
    assert first.read_bytes() == b"one"
    assert second is not None and second.name == "report(1).pdf"
    assert second.read_bytes() == b"two"
    assert third is not None and third.name == "report(2).pdf"
    assert third.read_bytes() == b"three"


def test_upload_archive_stores_excel_and_csv_in_separate_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_ARCHIVE_PATH", str(tmp_path))
    xlsx = upload_archive.archive_upload_bytes("District Tables.xlsx", b"PK\x03\x04-xlsx")
    csv = upload_archive.archive_upload_bytes("codes.csv", b"code,name\n1,A\n")
    pdf = upload_archive.archive_upload_bytes("report.pdf", b"%PDF")
    assert xlsx is not None and xlsx.name == "District Tables.xlsx"
    assert xlsx.parent.name == "excel_uploads"
    assert xlsx.read_bytes() == b"PK\x03\x04-xlsx"
    assert csv is not None and csv.name == "codes.csv"
    assert csv.parent.name == "csv_uploads"
    assert csv.read_bytes() == b"code,name\n1,A\n"
    assert pdf is not None and pdf.parent.name == "pdf_uploads"
    # Duplicate excel name gets (1) while keeping .xlsx
    again = upload_archive.archive_upload_bytes("District Tables.xlsx", b"other")
    assert again is not None and again.name == "District Tables(1).xlsx"
    assert again.parent.name == "excel_uploads"
    # Excel must not land in the PDF folder
    assert not (tmp_path / "pdf_uploads" / "District Tables.xlsx").exists()
    assert not (tmp_path / "pdf_uploads" / "codes.csv").exists()


def test_upload_archive_failure_is_best_effort(tmp_path, monkeypatch):
    """Archive errors must not raise — pipeline callers ignore the return value."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not-a-directory")
    monkeypatch.setenv("UPLOAD_ARCHIVE_PATH", str(blocked / "nested"))
    assert upload_archive.archive_upload_bytes("x.pdf", b"data") is None
