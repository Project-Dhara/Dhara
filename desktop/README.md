# Dhara Desktop (Windows)

Electron shell that bundles **PostgreSQL 16 + pgvector**, **FastAPI**, the **extraction job worker**, and **Next.js** for a local Windows install. Additive to this repo — it does **not** change the Docker / website deployment.

## What end users get

After you build on Windows/CI, distribute:

`desktop/release/Dhara-Setup-<version>-x64.exe`

Users double-click → Install → open **Dhara**. No Docker, Python, or Node required.

| Component | Role |
|-----------|------|
| Electron | Window, splash, single-instance, process lifecycle |
| PostgreSQL 16 + pgvector | Local DB under `%LOCALAPPDATA%\Dhara\pgdata` |
| Python 3.11 + backend | FastAPI API |
| `job_worker` | Extraction/upload jobs (`DHARA_INLINE_JOBS=false`, same as Compose) |
| Node + Next production build | UI with `/api` + `/mcp` rewrites |

LLM weights are **not** bundled. Users paste a provider key in Settings.

## Build the Setup installer (Windows x64)

```powershell
cd desktop
npm install
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1 -PgVectorZipUrl "<pg16-windows-pgvector-zip>"
```

Or step by step:

```powershell
.\scripts\fetch-win-deps.ps1 -PgVectorZipUrl "<optional>"
.\scripts\prepare-backend.ps1
.\scripts\prepare-frontend.ps1
npm install
npm run dist:win
```

Artifacts: `desktop/release/` (NSIS setup + portable).

### pgvector

EDB Postgres zips do not include pgvector. Supply a Windows PG16-compatible zip via `-PgVectorZipUrl`, or copy files into `resources/win-x64/pgsql/` (see `PGVECTOR_REQUIRED.txt`). The build refuses to package without `vector.dll`.

## Runtime layout

```
%LOCALAPPDATA%\Dhara\
  pgdata\
  object_store\
  logs\
  runtime.json
```

Services bind to `127.0.0.1` on high ports (defaults 55432 / 18000 / 18080).

## Developer: compile Electron shell only

```bash
cd desktop
npm install
npm run build
```

Without `resources/win-x64/*` populated, full app start will fail until Windows prepare scripts run.

## Smoke test

See [scripts/smoke-checklist.md](scripts/smoke-checklist.md).

## Code signing

NSIS builds are unsigned by default. For public distribution, add an Authenticode certificate in electron-builder / CI to reduce SmartScreen warnings.
