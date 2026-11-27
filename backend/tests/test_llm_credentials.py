"""Encrypted LLM credential storage and status responses."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

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


def test_encrypt_uses_auto_file_key_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_CREDENTIALS_KEY", raising=False)
    store = tmp_path / "object_store"
    monkeypatch.setenv("STORAGE_LOCAL_PATH", str(store))
    from app.core.config import clear_settings_cache

    clear_settings_cache()
    from app.core.crypto import decrypt_secret, encrypt_secret

    ct = encrypt_secret("sk-from-settings-ui")
    assert decrypt_secret(ct) == "sk-from-settings-ui"
    key_file = store.parent / ".llm_credentials_fernet_key"
    assert key_file.is_file()
    clear_settings_cache()


def test_redact_secrets():
    from app.core.logging import redact_secrets

    sample = 'Authorization: Bearer abc.def api_key="sk-live-123" password="pw"'
    out = redact_secrets(sample)
    assert "sk-live-123" not in out
    assert "abc.def" not in out
    assert "pw" not in out
    assert "***" in out


def test_get_status_includes_decrypted_api_key(fernet_env):
    """Owner status includes plaintext after successful decrypt."""
    from app.core.crypto import encrypt_secret
    from app.db.repositories import llm_keys as llm_repo

    session = MagicMock()
    row = MagicMock()
    row.api_key = encrypt_secret("sk-live-owner-key")
    row.provider = "openai"
    row.updated_at = datetime(2026, 1, 15, tzinfo=timezone.utc)

    original = llm_repo.get
    llm_repo.get = lambda _s, _e: row  # type: ignore
    try:
        status = llm_repo.get_status(session, "u@example.com")
        key, provider, base_url, model = llm_repo.get_decrypted(session, "u@example.com")
    finally:
        llm_repo.get = original

    assert status.configured is True
    assert status.crypto_error is False
    assert status.provider == "openai"
    assert status.api_key == "sk-live-owner-key"
    assert status.updated_at is not None
    assert key == "sk-live-owner-key"
    assert provider == "openai"
    assert base_url is None
    assert model is None


def test_get_status_crypto_error_when_decrypt_fails(fernet_env):
    """Tampered / wrong-key ciphertext → configured false + crypto_error."""
    from app.db.repositories import llm_keys as llm_repo

    session = MagicMock()
    row = MagicMock()
    # Looks like Fernet but is not valid under the current key.
    row.api_key = "gAAAA" + ("x" * 80)
    row.provider = "openai"
    row.updated_at = None

    original = llm_repo.get
    llm_repo.get = lambda _s, _e: row  # type: ignore
    try:
        status = llm_repo.get_status(session, "u@example.com")
        key, provider, base_url, model = llm_repo.get_decrypted(session, "u@example.com")
    finally:
        llm_repo.get = original

    assert status.configured is False
    assert status.crypto_error is True
    assert status.api_key is None
    assert status.provider == "openai"
    assert key is None
    assert provider is None
    assert base_url is None
    assert model is None


def test_get_status_legacy_plaintext(fernet_env):
    """Pre-encryption rows remain usable until re-saved."""
    from app.db.repositories import llm_keys as llm_repo

    session = MagicMock()
    row = MagicMock()
    row.api_key = "sk-legacy-plaintext"
    row.provider = "Anthropic"
    row.updated_at = None

    original = llm_repo.get
    llm_repo.get = lambda _s, _e: row  # type: ignore
    try:
        status = llm_repo.get_status(session, "u@example.com")
    finally:
        llm_repo.get = original

    assert status.configured is True
    assert status.crypto_error is False
    assert status.api_key == "sk-legacy-plaintext"
    assert status.provider == "anthropic"


def test_status_payload_shape(fernet_env):
    """HTTP payload helpers expose api_key only when configured."""
    from app.api.routes.llm_key import _status_payload
    from app.db.repositories.llm_keys import LlmKeyStatus

    ok = LlmKeyStatus(
        configured=True,
        provider="openai",
        updated_at="2026-01-01T00:00:00+00:00",
        api_key="sk-visible",
    )
    body = _status_payload(ok)
    assert body["configured"] is True
    assert body["api_key"] == "sk-visible"
    assert body["crypto_error"] is False

    bad = LlmKeyStatus(
        configured=False,
        provider="openai",
        updated_at=None,
        crypto_error=True,
    )
    body_bad = _status_payload(bad)
    assert body_bad["configured"] is False
    assert body_bad["api_key"] is None
    assert body_bad["crypto_error"] is True


def test_resolve_for_user_returns_decrypted(fernet_env):
    from app.core.crypto import encrypt_secret
    from app.db.repositories import llm_keys as llm_repo
    from app.services.credentials import service as credentials_service

    session = MagicMock()
    row = MagicMock()
    row.api_key = encrypt_secret("sk-for-provider")
    row.provider = "openai"
    row.base_url = None
    row.model = None
    row.updated_at = None

    original = llm_repo.get
    llm_repo.get = lambda _s, _e: row  # type: ignore
    try:
        key, provider = credentials_service.resolve_for_user(session, "u@example.com")
    finally:
        llm_repo.get = original

    assert key == "sk-for-provider"
    assert provider == "openai"


def test_resolve_for_user_strips_ollama_url_for_openai(fernet_env, monkeypatch):
    """Leftover self-hosted base_url must not route OpenAI saves to Ollama."""
    from app.core.crypto import encrypt_secret
    from app.db.repositories import llm_keys as llm_repo
    from app.services.credentials import service as credentials_service

    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    from app.core.config import clear_settings_cache

    clear_settings_cache()

    session = MagicMock()
    row = MagicMock()
    row.api_key = encrypt_secret("sk-live-openai")
    row.provider = "openai"
    row.base_url = "http://127.0.0.1:11434/v1"
    row.model = "gemma3:1b"
    row.updated_at = None

    original = llm_repo.get
    llm_repo.get = lambda _s, _e: row  # type: ignore
    try:
        creds = credentials_service.resolve_for_user(session, "u@example.com")
    finally:
        llm_repo.get = original
        clear_settings_cache()

    assert creds.api_key == "sk-live-openai"
    assert creds.provider == "openai"
    assert creds.base_url is None
    assert creds.model is None


def test_upsert_openai_clears_leftover_base_url(fernet_env):
    from app.db.repositories import llm_keys as llm_repo

    session = MagicMock()
    row = MagicMock()
    row.api_key = "old"
    row.provider = "self-hosted"
    row.base_url = "http://127.0.0.1:11434/v1"
    row.model = "gemma3:1b"

    original = llm_repo.get
    llm_repo.get = lambda _s, _e: row  # type: ignore
    try:
        out = llm_repo.upsert(
            session,
            "u@example.com",
            "sk-new-openai",
            "openai",
            base_url="http://127.0.0.1:11434/v1",
            model="gemma3:1b",
        )
    finally:
        llm_repo.get = original

    assert out is row
    assert row.provider == "openai"
    assert row.base_url is None
    assert row.model is None
    session.flush.assert_called()


def test_upsert_self_hosted_keeps_base_url(fernet_env):
    from app.db.repositories import llm_keys as llm_repo

    session = MagicMock()
    row = MagicMock()
    row.api_key = "old"
    row.provider = "openai"
    row.base_url = None
    row.model = None

    original = llm_repo.get
    llm_repo.get = lambda _s, _e: row  # type: ignore
    try:
        llm_repo.upsert(
            session,
            "u@example.com",
            "ollama",
            "self-hosted",
            base_url="http://127.0.0.1:11434/v1",
            model="gemma3:1b",
        )
    finally:
        llm_repo.get = original

    assert row.provider == "self-hosted"
    assert row.base_url == "http://127.0.0.1:11434/v1"
    assert row.model == "gemma3:1b"
