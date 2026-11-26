"""Desktop BGE embedder helpers (prefix, status, no Hub required)."""

from __future__ import annotations

import os

from app.services.classification.nco_embedder import (
    BGE_QUERY_PREFIX,
    clear_embedder,
    embedding_family,
    query_text_for_encode,
    retrieval_status,
    set_retrieval_status,
)


def test_bge_query_prefix(monkeypatch):
    monkeypatch.setenv("NCO_EMBEDDING_FAMILY", "bge")
    monkeypatch.delenv("NCO_EMBEDDING_MODEL", raising=False)
    assert embedding_family() == "bge"
    q = query_text_for_encode("software engineer")
    assert q.startswith(BGE_QUERY_PREFIX)
    assert q.endswith("software engineer")
    # Idempotent
    assert query_text_for_encode(q) == q


def test_non_bge_no_prefix(monkeypatch):
    monkeypatch.setenv("NCO_EMBEDDING_FAMILY", "embeddinggemma")
    monkeypatch.setenv("NCO_EMBEDDING_MODEL", "google/embeddinggemma-300m")
    assert query_text_for_encode("nurse") == "nurse"


def test_family_from_path(monkeypatch):
    monkeypatch.delenv("NCO_EMBEDDING_FAMILY", raising=False)
    monkeypatch.setenv(
        "NCO_EMBEDDING_MODEL",
        r"C:\Program Files\Dhara\resources\win-x64\models\embeddinggemma-300m",
    )
    assert embedding_family() == "embeddinggemma"
    assert query_text_for_encode("nurse") == "nurse"


def test_retrieval_status_roundtrip():
    clear_embedder()
    set_retrieval_status("keyword-only", "only 400 MB RAM available")
    st = retrieval_status()
    assert st["retrieval_mode"] == "keyword-only"
    assert "400" in st["retrieval_reason"]
    set_retrieval_status("semantic", "")
    assert retrieval_status()["retrieval_mode"] == "semantic"
