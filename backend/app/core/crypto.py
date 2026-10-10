"""Authenticated encryption for secrets stored in the database."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class CredentialCryptoError(RuntimeError):
    """Raised when encryption key is missing or ciphertext is invalid."""


def _fernet() -> Fernet:
    key = (get_settings().llm_credentials_key or "").strip()
    if not key:
        raise CredentialCryptoError(
            "LLM_CREDENTIALS_KEY is not set — generate a Fernet key and add it to the environment"
        )
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (ValueError, TypeError) as e:
        raise CredentialCryptoError(
            "LLM_CREDENTIALS_KEY is not a valid Fernet key"
        ) from e


def encrypt_secret(plaintext: str) -> str:
    """Return Fernet ciphertext (url-safe base64 text)."""
    if not plaintext:
        raise ValueError("cannot encrypt empty secret")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt Fernet ciphertext. Rejects empty values."""
    if not ciphertext:
        raise CredentialCryptoError("empty ciphertext")
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        raise CredentialCryptoError("invalid or tampered credential ciphertext") from e


def is_fernet_token(value: str) -> bool:
    """Heuristic: Fernet tokens are url-safe base64 starting with gAAAA."""
    return bool(value) and value.startswith("gAAAA")
