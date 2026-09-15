"""Login accounts (admin-provisioned; see backend/scripts/create_user.py)."""
import psycopg2.extras


def create_user(conn, email, password_hash, name=None, dept=None):
    """Provision (or update) a login. Admin-only — see create_user.py."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (email, password_hash, name, dept)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE
                SET password_hash = EXCLUDED.password_hash,
                    name          = COALESCE(EXCLUDED.name, users.name),
                    dept          = COALESCE(EXCLUDED.dept, users.dept)
        """, (email, password_hash, name, dept))
    conn.commit()


def get_user_by_email(conn, email):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT email, password_hash, name, dept FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
    return dict(row) if row else None
