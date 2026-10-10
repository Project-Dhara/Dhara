"""Per-user LLM API key storage (separate from ``users``)."""
import psycopg2.extras


def get_llm_api_key(conn, user_email: str):
    """Return ``{provider, api_key, updated_at}`` for this user, or None."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT provider, api_key, updated_at
              FROM llm_api_keys
             WHERE user_email = %s
            """,
            (user_email,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def upsert_llm_api_key(conn, user_email: str, api_key: str, provider: str | None = None):
    """Insert or replace the caller's stored key. ``api_key`` must be non-empty."""
    provider = (provider or "").strip() or None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO llm_api_keys (user_email, provider, api_key, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON CONFLICT (user_email) DO UPDATE
                SET provider   = EXCLUDED.provider,
                    api_key    = EXCLUDED.api_key,
                    updated_at = NOW()
            """,
            (user_email, provider, api_key),
        )
    conn.commit()


def delete_llm_api_key(conn, user_email: str) -> bool:
    """Remove the caller's stored key. Returns True if a row was deleted."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM llm_api_keys WHERE user_email = %s",
            (user_email,),
        )
        deleted = cur.rowcount > 0
    conn.commit()
    return deleted
