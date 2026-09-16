# ── Stage 1: Build the Next.js frontend ────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ── Stage 2: single runtime image with both Node (frontend) and Python
#    (backend) -- Next.js needs its own long-lived server process now (it's
#    no longer a static build FastAPI can just serve from disk), so this
#    container runs both processes: FastAPI listens internally on
#    BACKEND_PORT (never exposed), Next.js listens on the public PORT and
#    proxies /api/* to it via next.config.mjs's rewrites (BACKEND_ORIGIN).
FROM node:20-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Backend
COPY backend/requirements.txt ./backend/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r backend/requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"
COPY backend/ ./backend/

# Frontend (built) -- copy the whole app dir (standalone Next output isn't
# used here to keep this simple; `next start` needs node_modules + .next).
COPY --from=frontend /frontend /app/frontend

ENV BACKEND_PORT=8000
ENV BACKEND_ORIGIN=http://127.0.0.1:8000
ENV PORT=8080

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 8080
CMD ["/app/start.sh"]
