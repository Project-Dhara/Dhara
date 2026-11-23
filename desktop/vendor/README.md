# Desktop vendor payloads (offline / guided install)

Place **real** installers and image tarballs here before building `DharaSetup.exe`.
Do not add placeholder or dummy URLs in code — the app looks for these files first,
then falls back to official download endpoints only when missing.

## Expected files

| File | Purpose |
|------|---------|
| `Docker Desktop Installer.exe` | Official Docker Desktop for Windows |
| `OllamaSetup.exe` | Official Ollama Windows installer (local CPU LLM) |
| `dhara-backend-desktop.tar` | `docker save` of `dhara-backend:desktop` |
| `dhara-frontend-desktop.tar` | `docker save` of `dhara-frontend:desktop` |
| `pgvector-pg16.tar` | Optional offline copy of `pgvector/pgvector:pg16` |

## Build image tarballs (from repo root)

```bash
docker build -t dhara-backend:desktop ./backend
docker build -t dhara-frontend:desktop \
  --build-arg BACKEND_ORIGIN=http://backend:8000 \
  ./frontend
docker pull pgvector/pgvector:pg16
docker save dhara-backend:desktop -o desktop/vendor/dhara-backend-desktop.tar
docker save dhara-frontend:desktop -o desktop/vendor/dhara-frontend-desktop.tar
docker save pgvector/pgvector:pg16 -o desktop/vendor/pgvector-pg16.tar
```

Official downloads (when not bundling):

- Docker Desktop: https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe
- Ollama: https://ollama.com/download/OllamaSetup.exe
