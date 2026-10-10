#!/bin/sh
# Apply Alembic migrations once before the API process starts (idempotent at head).
set -e
cd "${DHARA_BACKEND_DIR:-/backend}"

case "${SKIP_DB_MIGRATIONS:-}" in
  1|true|TRUE|yes|YES) ;;
  *)
    echo "Applying database migrations (alembic upgrade head)..."
    alembic upgrade head
    ;;
esac

exec "$@"
