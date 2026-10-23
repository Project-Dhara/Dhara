"""Adaptive multi-file batch concurrency (large PDF reports vs light files)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workers import upload_batches as ub


def test_env_override_disables_adaptive(monkeypatch):
    monkeypatch.setenv("PDF_BATCH_FILE_CONCURRENCY", "3")
    heavy = [
        {"status": "queued", "source_type": "pdf", "page_count": 220, "size_bytes": 6_000_000},
        {"status": "queued", "source_type": "pdf", "page_count": 200, "size_bytes": 5_000_000},
    ]
    assert ub.resolve_batch_file_concurrency(heavy) == 3


def test_light_files_keep_host_parallelism(monkeypatch):
    monkeypatch.delenv("PDF_BATCH_FILE_CONCURRENCY", raising=False)
    with mock.patch.object(ub.os, "cpu_count", return_value=2):
        light = [
            {"status": "queued", "source_type": "excel", "page_count": 0, "size_bytes": 80_000},
            {"status": "queued", "source_type": "csv", "page_count": 0, "size_bytes": 20_000},
        ]
        assert ub.resolve_batch_file_concurrency(light) == 2


def test_heavy_pdfs_stay_parallel_when_ram_ok(monkeypatch):
    monkeypatch.delenv("PDF_BATCH_FILE_CONCURRENCY", raising=False)
    with mock.patch.object(ub.os, "cpu_count", return_value=2), mock.patch(
        "app.services.llm_prompts._available_ram_mb", return_value=6000
    ):
        heavy = [
            {"status": "queued", "source_type": "pdf", "page_count": 227, "size_bytes": 6_500_000},
            {"status": "queued", "source_type": "pdf", "page_count": 180, "size_bytes": 5_000_000},
        ]
        assert ub.resolve_batch_file_concurrency(heavy) == 2


def test_very_heavy_pdfs_serialize_only_when_ram_tight(monkeypatch):
    monkeypatch.delenv("PDF_BATCH_FILE_CONCURRENCY", raising=False)
    with mock.patch.object(ub.os, "cpu_count", return_value=2), mock.patch(
        "app.services.llm_prompts._available_ram_mb", return_value=2800
    ):
        heavy = [
            {"status": "queued", "source_type": "pdf", "page_count": 227, "size_bytes": 6_500_000},
            {"status": "queued", "source_type": "pdf", "page_count": 200, "size_bytes": 6_000_000},
        ]
        assert ub.resolve_batch_file_concurrency(heavy) == 1


def test_is_heavy_pdf_thresholds():
    assert ub._is_heavy_pdf("pdf", page_count=80, size_bytes=0)
    assert ub._is_heavy_pdf("pdf", page_count=0, size_bytes=4 * 1024 * 1024)
    assert not ub._is_heavy_pdf("excel", page_count=0, size_bytes=10_000_000)
    assert ub._is_very_heavy_pdf(page_count=150, size_bytes=0)
    assert not ub._is_very_heavy_pdf(page_count=90, size_bytes=3_000_000)
