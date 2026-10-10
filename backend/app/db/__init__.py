"""Database session, ORM models, and repositories.

Live access uses ``psycopg2`` via ``catalogue.db.get_connection`` and
request-time ``init_schema()``. SQLAlchemy 2.x and Alembic arrive in
Phase 3. Distinct from ``backend/db/`` (Docker ``init-pgvector.sql``).
"""
