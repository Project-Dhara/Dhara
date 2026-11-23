# Desktop vendor payloads (offline / guided install)

Place **real** installers and image tarballs here before building `DharaSetup.exe`.
Do not add placeholder or dummy URLs in code — the app looks for these files first,
then falls back to official download endpoints only when missing.

## Expected files

| File | Purpose | Bundled into `DharaSetup.exe`? |
|------|---------|--------------------------------|
| `Docker Desktop Installer.exe` | Official Docker Desktop for Windows | Yes (if present) |
| `OllamaSetup.exe` | Official Ollama Windows installer (local CPU LLM) | Yes (if present) |
| `dhara-backend-desktop.tar` | `docker save` of `dhara-backend:desktop` | **No** — excluded (NSIS mmap fails on multi‑GB archives) |
| `dhara-frontend-desktop.tar` | `docker save` of `dhara-frontend:desktop` | **No** |
| `pgvector-pg16.tar` | Optional offline copy of `pgvector/pgvector:pg16` | **No** |

Keep the `.tar` files for `docker load` on a target machine or CI. Do not rely on
embedding them in the NSIS installer.

## Build image tarballs (from repo root)

**Windows (PowerShell)** — preferred; does not need bash or Make:

```powershell
.\desktop\scripts\build-images.ps1
```

**macOS / Linux / Git Bash / WSL:**

```bash
bash desktop/scripts/build-images.sh
# or: make desktop-images
```

**Manual Docker commands** (any shell with Docker on PATH):

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

On Windows PowerShell, the same commands use backslashes, for example
`.\backend` and `desktop\vendor\...`.

Official downloads (when not bundling):

- Docker Desktop: https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe
- Ollama: https://ollama.com/download/OllamaSetup.exe
