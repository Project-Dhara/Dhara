"""Authenticated encryption for secrets stored in the database."""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class CredentialCryptoError(RuntimeError):
    """Raised when encryption key is missing or ciphertext is invalid."""


def _llm_credentials_key_file() -> Path:
    """Persistent server key for encrypting user LLM keys in Postgres (not user-facing)."""
    root = Path(get_settings().storage_local_path).expanduser().resolve().parent
    return root / ".llm_credentials_fernet_key"


def _load_or_create_file_key() -> str:
    path = _llm_credentials_key_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    generated = Fernet.generate_key().decode("ascii")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        key = path.read_text(encoding="utf-8").strip()
        if not key:
            raise CredentialCryptoError(
                f"LLM credentials key file {path} exists but is empty"
            ) from None
        return key
    try:
        os.write(fd, generated.encode("utf-8"))
    finally:
        os.close(fd)
    return generated


def _resolve_fernet_key() -> str:
    key = (get_settings().llm_credentials_key or "").strip()
    if key:
        return key
    # Local dev: auto-provision so Settings → POST /api/llm-key can encrypt into DB
    # without putting the user's provider key in .env.
    return _load_or_create_file_key()


def _fernet() -> Fernet:
    key = _resolve_fernet_key()
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
