#!/bin/bash
# Runs both processes in one container: FastAPI internally on
# BACKEND_PORT (never exposed publicly), Next.js on the public PORT.
# next.config.mjs's rewrites proxy /api/* from Next to FastAPI via
# BACKEND_ORIGIN, so the browser only ever talks to the Next.js port.
set -e

cd /app/backend
uvicorn main:app --host 0.0.0.0 --port "${BACKEND_PORT:-8000}" &
BACKEND_PID=$!

cd /app/frontend
npm run start -- -p "${PORT:-8080}" &
FRONTEND_PID=$!

# If either process dies, exit so the container restarts cleanly rather
# than silently running half-broken.
wait -n "$BACKEND_PID" "$FRONTEND_PID"
exit $?
