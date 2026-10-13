"""Unit tests for PDF table snapshot rendering helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.extraction.pdf.snapshots import (
    build_snapshots_for_result,
    parse_batch_table_namespace,
    physical_page_number,
    resolve_snapshot_storage_target,
)


def test_build_snapshots_for_result_empty_inputs():
    assert build_snapshots_for_result(b"", {1: {"tables": []}}) == {}
    assert build_snapshots_for_result(b"%PDF", None) == {}
    assert build_snapshots_for_result(b"%PDF", {}) == {}


def test_parse_batch_table_namespace():
    assert parse_batch_table_namespace("12-0") is None
    assert parse_batch_table_namespace("__f0__100-0") == (0, "100-0")
    assert parse_batch_table_namespace("__f1__3-2") == (1, "3-2")


def test_resolve_snapshot_storage_target_batch_child():
    job = {
        "job_id": "batch1",
        "source_type": "batch",
        "result": {
            "__batch_meta__": {
                "batch_files": [
                    {"file_job_id": "childA", "filename": "a.pdf"},
                    {"file_job_id": "childB", "filename": "b.pdf"},
                ]
            }
        },
    }
    assert resolve_snapshot_storage_target(job, "__f0__100-0") == ("childA", "100-0")
    assert resolve_snapshot_storage_target(job, "__f1__3-0") == ("childB", "3-0")
    assert resolve_snapshot_storage_target(job, "12-0") == ("batch1", "12-0")


def test_physical_page_number_strips_batch_prefix():
    assert physical_page_number({"page": 100}, "__f0__100") == 100
    assert physical_page_number({}, "__f0__100") == 100
    assert physical_page_number({}, "12") == 12


def test_build_snapshots_for_result_renders_each_table():
    result = {
        1: {
            "tables": [
                {"page": 1, "bbox": [10, 20, 100, 200]},
                {"page": 1, "bbox": [10, 220, 100, 400]},
            ]
        },
        "__batch_meta__": {"batch_files": []},
    }
    fake_pix = MagicMock()
    fake_pix.tobytes.return_value = b"PNGDATA"
    fake_page = MagicMock()
    fake_page.rect.x1 = 500
    fake_page.rect.y1 = 700
    fake_page.get_pixmap.return_value = fake_pix
    fake_doc = MagicMock()
    fake_doc.page_count = 1
    fake_doc.__getitem__.return_value = fake_page

    with patch("pymupdf.open", return_value=fake_doc):
        out = build_snapshots_for_result(b"%PDF-fake", result)

    assert set(out.keys()) == {"1-0", "1-1"}
    assert out["1-0"] == b"PNGDATA"
    assert fake_page.get_pixmap.call_count == 2
    fake_doc.close.assert_called_once()
