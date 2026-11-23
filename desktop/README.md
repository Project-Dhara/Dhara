# Dhara Desktop (Windows)

Electron shell that installs and runs the local Dhara stack (Postgres, API,
worker, UI) on Windows, with optional **Ollama** for CPU LLMs.

## For users and beginners

Follow the full setup guide:

**[Windows desktop setup](../docs/deployment/desktop-windows.md)**

That document covers:

1. PC requirements (Windows version, 8 GB RAM, ports)
2. Building `DharaSetup.exe` when you only have the source
3. Installing the app
4. First-run wizard (Docker, WSL, Ollama)
5. First login and Self-hosted / cloud LLM settings
6. Everyday use, data location, and troubleshooting

## For developers (short)

On **Windows PowerShell** (recommended; `bash` and `make` are often missing):

```powershell
# From repo root — build/export images into desktop/vendor/
.\desktop\scripts\build-images.ps1
# If blocked: powershell -ExecutionPolicy Bypass -File .\desktop\scripts\build-images.ps1
```

On macOS/Linux, or Windows with Git Bash / WSL / Make:

```bash
# From repo root — build/export images into desktop/vendor/
bash desktop/scripts/build-images.sh
# or: make desktop-images
```

Optionally place official installers in [`vendor/`](vendor/) (see
[`vendor/README.md`](vendor/README.md)):

- `Docker Desktop Installer.exe`
- `OllamaSetup.exe`

Then on Windows with Node 20+ (use `npm.cmd` or bypass execution policy if
PowerShell blocks `npm.ps1`):

```powershell
cd desktop
cmd /c "npm install && npm run dist"   # produces desktop\dist\DharaSetup-*.exe
# Dev UI: Set-ExecutionPolicy -Scope Process Bypass; npm install; npm start
```

Image `.tar` files under `vendor/` are **not** packed into the installer (avoids
NSIS `mmap` failures). Docker/Ollama `.exe` installers in `vendor/` are included
when present.

Ship or run `DharaSetup-*.exe`, then continue from
[Part 1 of the setup guide](../docs/deployment/desktop-windows.md#part-1--install-the-app).
