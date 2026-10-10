"""
Login auth: password hashing + JWT issuance/verification.

Compatibility shim — prefer ``app.core.security``. JWT ``sub`` is the user UUID.
"""
from app.core.security import (  # noqa: F401
    EMAIL_RE,
    JWT_ALG,
    create_token,
    decode_token,
    decode_token_payload,
    hash_password,
    is_valid_org_email,
    verify_password,
)


def email_from_request(request) -> str:
    """Legacy helper — prefer FastAPI ``require_user`` / ``CurrentUser``."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise ValueError("Missing bearer token")
    token = header[len("bearer ") :].strip()
    if not token:
        raise ValueError("Missing bearer token")
    try:
        from app.api.dependencies import require_user
        from app.db.session import get_session_factory
        from app.core import security

        user_id = security.decode_token(token)
        session = get_session_factory()()
        try:
            from app.db.repositories import users as user_repo

            user = user_repo.get_by_id(session, user_id)
            if not user:
                raise ValueError("Account not found")
            return user.email
        finally:
            session.close()
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Invalid or expired token: {e}") from e
