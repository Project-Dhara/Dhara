"""
Login auth: password hashing + JWT issuance/verification.

Accounts are admin-provisioned only (see create_user.py) — there is no
public signup endpoint. Every write-path API route requires a valid
bearer token, and the email it carries is what data gets stored under.
"""

import os
import re
import time

import bcrypt
import jwt

# name@organization.domain — local part, then a domain with at least one dot.
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

JWT_ALG = "HS256"
JWT_EXP_SECONDS = 60 * 60 * 12  # 12 hours


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is not set")
    return secret


def is_valid_org_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip()))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, AttributeError):
        return False


def create_token(email: str) -> str:
    payload = {"sub": email, "exp": int(time.time()) + JWT_EXP_SECONDS}
    return jwt.encode(payload, _secret(), algorithm=JWT_ALG)


def decode_token(token: str) -> str:
    """Return the email ("sub" claim) carried by a valid, unexpired token."""
    payload = jwt.decode(token, _secret(), algorithms=[JWT_ALG])
    return payload["sub"]


def email_from_request(request) -> str:
    """Extract and verify the bearer token on an incoming request.

    Raises ValueError (caller maps this to HTTP 401) if the token is
    missing, malformed, or expired.
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise ValueError("Missing bearer token")
    token = header[len("bearer "):].strip()
    if not token:
        raise ValueError("Missing bearer token")
    try:
        return decode_token(token)
    except jwt.PyJWTError as e:
        raise ValueError(f"Invalid or expired token: {e}")
