"""Legacy DBAPI access via the SQLAlchemy engine pool.

New code must use ``app.db.session.session_scope`` / ``get_db``.
This module remains only for cursor-based helpers not yet ported.
It does **not** open a separate ``psycopg2.connect`` — connections come
from the SQLAlchemy pool. Request-time DDL is a no-op (Alembic owns schema).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_connection():
    """Return a pooled DBAPI connection (caller must ``close()``)."""
    from app.db.session import get_engine

    return get_engine().raw_connection()


def init_schema(conn) -> None:
    """No-op — schema is owned by Alembic (``DISABLE_REQUEST_TIME_DDL`` default)."""
    del conn
    return
