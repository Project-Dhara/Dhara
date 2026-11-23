-- Runs only on first Postgres data-dir init (docker-entrypoint-initdb.d).
-- Existing volumes also get the extension via catalogue.init_schema().
CREATE EXTENSION IF NOT EXISTS vector;
