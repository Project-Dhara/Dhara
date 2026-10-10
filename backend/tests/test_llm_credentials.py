"""Encrypted LLM credential storage and status responses."""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet


@pytest.fixture()
def fernet_env(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("LLM_CREDENTIALS_KEY", key)
    from app.core.config import clear_settings_cache

    clear_settings_cache()
    yield key
    clear_settings_cache()


def test_encrypt_decrypt_round_trip(fernet_env):
    from app.core.crypto import decrypt_secret, encrypt_secret, is_fernet_token

    ct = encrypt_secret("sk-test-secret")
    assert is_fernet_token(ct)
    assert decrypt_secret(ct) == "sk-test-secret"
    assert ct != "sk-test-secret"


def test_redact_secrets():
    from app.core.logging import redact_secrets

    sample = 'Authorization: Bearer abc.def api_key="sk-live-123" password="pw"'
    out = redact_secrets(sample)
    assert "sk-live-123" not in out
    assert "abc.def" not in out
    assert "pw" not in out
    assert "***" in out


def test_llm_key_status_shape(fernet_env):
    """Repository status never includes the raw key."""
    from unittest.mock import MagicMock

    from app.db.repositories import llm_keys as llm_repo

    session = MagicMock()
    row = MagicMock()
    row.api_key = "gAAAA" + "x" * 80
    row.provider = "openai"
    row.updated_at = None
    session.scalar.return_value = row

    # Bypass DB: call get_status with patched get
    original = llm_repo.get
    llm_repo.get = lambda _s, _e: row  # type: ignore
    try:
        status = llm_repo.get_status(session, "u@example.com")
    finally:
        llm_repo.get = original
    assert status.configured is True
    assert status.provider == "openai"
    assert not hasattr(status, "api_key")
