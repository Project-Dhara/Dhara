# Dhara Desktop (Windows)

A self-contained Electron app. Installing `DharaSetup-<version>-x64.exe` gives a non-technical user
everything Dhara needs — there is nothing else to install and nothing to configure:

| Piece | How it ships |
|-------|--------------|
| **PostgreSQL 16 + pgvector** | Native `pgsql\` binaries (incl. `pg_dump.exe`), listening on `127.0.0.1` only |
| **API + web UI** | Bundled embeddable Python 3.11 runs `uvicorn main:app` on `127.0.0.1`; it serves the static (exported) UI, `/api` and `/mcp` on **one** port |
| **Background jobs** | A separate `python -m app.workers.job_worker` process (PDF / Excel / CSV work never runs inside the API) |
| **Shell** | Electron: splash, tray, one window pointed at the API origin |

There is no Docker, WSL, Compose, or Node.js server at runtime. Cloud / API-key LLMs are the default;
a local model via [Ollama](https://ollama.com) is an explicit opt-in from Settings — Dhara never
downloads, installs, or starts Ollama.

## What the app does at startup

`ServiceSupervisor` (`src/main/supervisor.ts`) runs these steps and shows progress on the splash screen:

1. **Preflight** — checks the bundled runtime is present; refuses to start if Dhara was launched
   *Run as administrator* (Postgres will not run elevated); soft-warns below 8 GB RAM.
2. **Earlier session** — removes a stale `postmaster.pid` (dead PID, or PID reused by another program);
   adopts a live Dhara Postgres/API left running by “Keep services running on quit”; refuses (without
   deleting anything) if a live *foreign* process holds the data directory.
3. **Ports** — prefers **55432** (Postgres) and **18000** (API). If a port is busy it allocates a free
   loopback port; the window URL, `DATABASE_URL`, and all child environments use the real ports.
4. **Secrets** — per-install `JWT_SECRET`, `LLM_CREDENTIALS_KEY`, `MCP_AUTH_TOKEN`, and DB password,
   generated once and stored in `%LOCALAPPDATA%\Dhara\runtime.json`.
5. **Postgres** — `initdb` on first run, rewrites a managed block in `postgresql.conf` (profile below),
   starts `postgres.exe` directly, creates the `dhara` database and extensions.
6. **Backup + migrate** — compares the database's Alembic revision with the one shipped in this build.
   If they differ and the database already holds data: disk-space check → bundled `pg_dump.exe` backup
   (cold `pgdata` copy as fallback) → `alembic upgrade head`. **If the backup fails, migration is
   skipped and startup stops with an explanation.** Same revision ⇒ no backup, no migrate.
7. **API** — `uvicorn` bound to `127.0.0.1`, then waits for `/api/ready`.
8. **Worker** — starts the job worker; if it crashes it is restarted with back-off while the API stays up.
9. The window loads `http://127.0.0.1:<apiPort>`.

All children are assigned to a **Windows Job Object with kill-on-close**, so force-killing Electron
(Task Manager, crash, power-off of the session) also stops Postgres, the API, and the worker and
releases `pgdata`.

### Postgres memory profile

Written to `pgdata\postgresql.conf` between `# >>> dhara-desktop-profile` markers on every start:

| Setting | ~8 GB host | ≥ 16 GB host |
|---------|-----------|--------------|
| `listen_addresses` | `127.0.0.1` | `127.0.0.1` |
| `shared_buffers` | `128MB` | `256MB` |
| `work_mem` | `4MB` | `8MB` |
| `maintenance_work_mem` | `64MB` | `128MB` |
| `max_connections` | `20` | `40` |
| `effective_cache_size` | `512MB` | `2GB` |
| `max_wal_size` | `256MB` | `512MB` |
| `checkpoint_completion_target` | `0.9` | `0.9` |
| `random_page_cost` | `1.1` | `1.1` |

PDF processing limits (`PDF_CPU_WORKERS`, `PDF_BATCH_FILE_CONCURRENCY`, …) and DB pool sizes scale the
same way. `MALLOC_ARENA_MAX` is never set (it is a glibc setting) and `DHARA_INLINE_JOBS` is never set.

### Environment given to the API

`DATABASE_URL` (actual Postgres port), `JWT_SECRET`, `LLM_CREDENTIALS_KEY`, `DHARA_STATIC_UI_ROOT`
(the bundled `frontend\`), `MCP_HTTP_AUTH=token` + per-install `MCP_AUTH_TOKEN`,
`DHARA_LISTEN_HOST=127.0.0.1`, `DHARA_ALLOWED_HOSTS`, `DHARA_CORS_ORIGINS`, `DHARA_DATA_DIR`,
`STORAGE_LOCAL_PATH`, `UPLOAD_ARCHIVE_PATH`, `DHARA_MIN_AVAILABLE_RAM_MB=1200`, `NCO_EMBEDDING_MODEL=`
(TF-IDF only), and the `PDF_*` limits. See `src/main/backend-env.ts`.

## Using the tray

Open Dhara · Start services · Stop services · **Keep services running on quit** · Open logs folder ·
Copy diagnostics · Quit. Closing the window only hides it. With *Keep services running* ticked,
Quit leaves Postgres/API/worker running (their kill-on-close is lifted) and the next launch re-adopts
them; otherwise Quit stops worker → API → Postgres in order. `Dhara.exe --quit` asks a running
instance to quit the same way.

## Where things live

```
%LOCALAPPDATA%\Dhara\
  pgdata\          PostgreSQL cluster
  data\            object store, upload archive, PDF extraction output
  logs\            desktop.log, postgres.log, api.log, worker.log  (size-bounded)
  backups\         pre-migrate-<version>-<timestamp>.dump  (last 3 kept)
  runtime.json     ports, secrets, schema/backup facts   — never copied into backups
  auth.bin         signed-in session, encrypted with Windows DPAPI (Electron safeStorage)
  electron\        Chromium profile
```

**Backups contain your Dhara data (including encrypted LLM keys). Do not share the `backups` folder.**
Secrets stay in `runtime.json`, which is not part of any dump. Keep `runtime.json`: without it an existing
database cannot be opened (the app will say so rather than touching your data).

## Renderer bridge (`window.dharaDesktop`)

| API | Purpose |
|-----|---------|
| `readUploadFile(file)` | Reads a user-picked file in the main process (`fs:read-upload-file`; pdf/xlsx/xls/csv, ≤ 200 MB) |
| `getAuth()` / `setAuth({token,user})` / `clearAuth()` | Session persistence that survives a port change (localStorage is origin-scoped) |
| `getInfo()`, `openLogsFolder()`, `copyDiagnostics()` | Support helpers for Settings → Help |
| `ollama.status()` / `ollama.openDownloadPage()` | Read-only helpers for the optional local model (`http://127.0.0.1:11434/v1`) |

IPC is only honoured from the top frame of the app's own loopback origin.

## Developing

Requirements: Windows 10/11 x64, Node 20+, PowerShell 5.1+, Git. For the pgvector build step also
Visual Studio C++ Build Tools. Python and Postgres are downloaded for you.

```powershell
cd desktop
npm install

# 1. PostgreSQL + embeddable Python (+ pgvector)
npm run fetch-deps -- -BuildPgVector          # or: -PgVectorSource <zip with vector.dll/.control/.sql>

# 2. Python packages + backend sources  → resources\win-x64\{python,backend}
npm run prepare-backend

# 3. Static UI export (DHARA_DESKTOP_STATIC=1) → resources\win-x64\frontend
npm run prepare-frontend

# 4. Run from source
npm start
```

`pgvector` has no official Windows binaries, so supply it with `-BuildPgVector` (needs Git + MSVC) or
`-PgVectorSource`. Without it the database schema cannot be created; `build-installer.ps1` refuses to
package without it unless you pass `-AllowNoPgVector`.

`prepare-frontend.ps1` builds a scratch copy of `frontend/` with `DHARA_DESKTOP_STATIC=1` and expects
Next to emit a static export to `out/`, which is copied to `resources\win-x64\frontend`.

### Build the installer

```powershell
npm run dist                                   # runs all steps below, then electron-builder
# or step by step
powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1 -BuildPgVector
```

Output: `release\DharaSetup-<version>-x64.exe` (NSIS, per-user install, no admin prompt). Uninstalling
keeps `%LOCALAPPDATA%\Dhara` unless you answer **No** to “Keep your Dhara data?”; silent uninstalls and
upgrades always keep it. Typical payload ≈ 400–500 MB (no PyTorch/embedding models by default; add
`-IncludeEmbeddings` to `build-installer.ps1` to include them).

### Source layout

```
src/main/        TypeScript main process (compiled to dist/main, entry dist/main/index.js)
  supervisor.ts  service orchestration, restarts, adoption, shutdown
  postgres.ts    initdb, postgresql.conf profile, stale-pid recovery, SQL helpers
  backup.ts      disk check, pg_dump / cold copy, retention
  job-object.ts  Windows Job Object (kill-on-close) via resources/helpers/job-host.ps1
  backend-env.ts environment for API / worker / Alembic
  ports.ts, sysinfo.ts, runtime-state.ts, auth-store.ts, diagnostics.ts, ipc.ts, tray.ts, windows.ts …
src/preload/     sandboxed preloads (app window, splash)
src/renderer/    splash.html
scripts/         fetch-win-deps / prepare-backend / prepare-frontend / build-installer / installer.nsh
resources/       logo, helpers/ (PowerShell helpers); win-x64/ is generated and git-ignored
```

## Troubleshooting

| Symptom | What to do |
|---------|-----------|
| “Dhara cannot run with administrator rights” | Close Dhara and open it normally (not “Run as administrator”). |
| “could not open a local network port” | Another program or security tool blocks loopback ports. Close it or restart the PC. |
| “could not start its local database” | Tray → **Open logs folder** and send `postgres.log` / `desktop.log`. Never delete `pgdata` or `backups`. |
| Database “in use by another program” | Close other copies of Dhara (tray, Task Manager). A stale lock file after a crash is cleaned automatically. |
| “Not enough free disk space to back up your data” | Free space (about 1.5× your database size, minimum 2 GB) and start again. Nothing was changed. |
| Support request | Tray → **Copy diagnostics** and paste the text into your email. It contains no secrets or catalogue data. |

Local MCP clients must send the per-install token (`Authorization: Bearer <MCP_AUTH_TOKEN>`, found in
`runtime.json`); the steward UI does not need it. Data from earlier Docker-volume installs is not imported.
