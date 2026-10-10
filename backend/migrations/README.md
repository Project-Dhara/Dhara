# Migrations

Alembic is **not** configured in Phase 1.

Schema today is applied at request time via `catalogue.db.init_schema()`
(and nested PDF / staging / pgvector setup). Docker may also run
`backend/db/init-pgvector.sql` on first Postgres init.

Phase 3 will introduce SQLAlchemy 2.x + Alembic here. Requirements:

- Baseline existing tables without dropping data
- No automatic migration on every API startup
- Keep `/api/ready` read-only (no DDL)
- Include additive tables such as `llm_api_keys` when baselining
