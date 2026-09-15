"""KYDS (Know Your Dataset) form submissions."""
import json

import psycopg2.extras


def save_kyds_entry(conn, responses, user=None):
    """Persist a KYDS (Know Your Dataset) form submission for later use."""
    user = user or {}
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kyds_entries (user_email, user_name, user_dept, responses)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (
            user.get("email"),
            user.get("name"),
            user.get("dept"),
            json.dumps(responses),
        ))
        entry_id = cur.fetchone()[0]
    conn.commit()
    return entry_id


def get_latest_kyds_responses(conn, user_email):
    """Returns the most recent KYDS form responses submitted by this user, or
    None if this user hasn't submitted one. Used to ground Stage 4 LLM
    metadata generation in real, DB-stored context -- deliberately no
    fallback to another user's entry: if this user hasn't done KYDS, Stage 4
    must not fabricate metadata from a stranger's answers, and should leave
    the fields for manual entry instead."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT responses FROM kyds_entries
            WHERE user_email = %s
            ORDER BY created_at DESC LIMIT 1
        """, (user_email,))
        row = cur.fetchone()
    return row["responses"] if row else None


def get_own_latest_kyds_entry(conn, user_email):
    """Returns this user's own most recent KYDS submission (id, responses,
    created_at), or None — used to show/edit "your" KYDS entry in the
    console."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id, responses, created_at FROM kyds_entries
            WHERE user_email = %s
            ORDER BY created_at DESC LIMIT 1
        """, (user_email,))
        row = cur.fetchone()
    return dict(row) if row else None
