"""Engine and session factory.

Live: ``catalogue.db.get_connection()`` using ``DATABASE_URL``.
Phase 3 will add pooled SQLAlchemy sessions with configurable pool size,
TLS, and timeouts.
"""
