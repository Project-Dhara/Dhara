"""JWT helpers: UUID ``sub``, expiry, and invalid tokens."""
from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import jwt
import pytest

from app.core import security
from app.core.config import clear_settings_cache


@pytest.fixture(autouse=True)
def _jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-auth-jwt")
    monkeypatch.setenv("JWT_EXP_SECONDS", "3600")
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_create_token_sub_is_uuid():
    user_id = uuid.uuid4()
    token = security.create_token(user_id, email="alice@example.org")
    payload = jwt.decode(token, "test-secret-for-auth-jwt", algorithms=["HS256"])
    assert payload["sub"] == str(user_id)
    assert payload.get("email") == "alice@example.org"
    decoded = security.decode_token(token)
    assert decoded == user_id


def test_decode_token_rejects_email_sub():
    """Legacy email-as-sub tokens must fail (UUID-only policy)."""
    token = jwt.encode(
        {"sub": "alice@example.org", "exp": int(time.time()) + 3600},
        "test-secret-for-auth-jwt",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(token)


def test_decode_token_rejects_expired():
    user_id = uuid.uuid4()
    with patch.object(security, "_secret", return_value="test-secret-for-auth-jwt"):
        token = jwt.encode(
            {"sub": str(user_id), "exp": int(time.time()) - 10},
            "test-secret-for-auth-jwt",
            algorithm="HS256",
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            security.decode_token(token)


def test_decode_token_rejects_tampered_signature():
    user_id = uuid.uuid4()
    token = security.create_token(user_id)
    bad = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(jwt.PyJWTError):
        security.decode_token(bad)
