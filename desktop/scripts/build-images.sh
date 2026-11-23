#!/usr/bin/env bash
# Build and export desktop container images into desktop/vendor/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENDOR="$ROOT/desktop/vendor"
mkdir -p "$VENDOR"

echo "Building dhara-backend:desktop…"
docker build -t dhara-backend:desktop "$ROOT/backend"

echo "Building dhara-frontend:desktop…"
docker build -t dhara-frontend:desktop \
  --build-arg BACKEND_ORIGIN=http://backend:8000 \
  "$ROOT/frontend"

echo "Pulling postgres/pgvector…"
docker pull pgvector/pgvector:pg16

echo "Saving tarballs…"
docker save dhara-backend:desktop -o "$VENDOR/dhara-backend-desktop.tar"
docker save dhara-frontend:desktop -o "$VENDOR/dhara-frontend-desktop.tar"
docker save pgvector/pgvector:pg16 -o "$VENDOR/pgvector-pg16.tar"

echo "Done. Place Docker Desktop + Ollama installers in $VENDOR for offline setup."
