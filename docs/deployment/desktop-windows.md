# Dhara Desktop for Windows — setup guide

This guide explains how to run **Dhara as a local desktop app on Windows**.
You do not open the public website. Everything (database, API, UI) runs on
**your PC**, and your data stays on that PC.

If you want Docker Compose on a server instead, use [On-prem deployment](./on-prem.md).

---

## What you will get

| Item | Description |
|------|-------------|
| App icon | **Dhara** on the Desktop and Start Menu |
| Local stack | Bundled PostgreSQL, API, job worker, and UI (no Docker required) |
| AI assist | **Cloud API key** recommended in Settings; optional local **Ollama** (bundled; starts on opt-in) |
| Persistence | Closing the app keeps your catalogue, jobs, and settings |

This is **not** a browser shortcut to the public Dhara website.

---

## Before you begin (checklist)

| Check | Requirement |
|-------|-------------|
| Operating system | Windows **10 22H2 or newer** or Windows **11** |
| Memory | **8 GB RAM recommended** (install still works below 8 GB with a warning; 16 GB+ allows higher processing limits) |
| Disk space | About **20 GB free** (and extra free space before app updates that migrate the database) |
| Free ports | Preferred **18000** (app) and **55432** (database). If busy, Dhara picks other free local ports automatically |
| Admin rights | Install as a normal user. Do **not** “Run as administrator” (Postgres will refuse to start) |

**Tips for 8 GB PCs**

- Close browsers and other heavy apps during large PDF jobs.
- Need about **1.2 GB free RAM** before starting a PDF job.
- Prefer a cloud LLM key; local models use more memory.

---

## Choose your path

| Who you are | Start here |
|-------------|------------|
| You already have **`DharaSetup-*.exe`** | [Part 1 — Install the app](#part-1--install-the-app) |
| You only have the **source code** | [Part 0 — Build the installer](#part-0--build-the-installer-developers) first |

---

## Part 0 — Build the installer (developers)

1. Install **Node.js 20+**.
2. From the repo root, prepare Windows runtimes and package the app:

```powershell
cd desktop
npm install
powershell -ExecutionPolicy Bypass -File .\scripts\fetch-win-deps.ps1
# Provide pgvector for Postgres 16 (required): -BuildPgVector or -PgVectorSource <zip>
powershell -ExecutionPolicy Bypass -File .\scripts\prepare-backend.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\prepare-frontend.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1
```

Installer output:

```text
desktop\release\DharaSetup-<version>-x64.exe
```

See [`desktop/README.md`](../../desktop/README.md) for script details.

---

## Part 1 — Install the app

1. Double-click **`DharaSetup-*.exe`**.
2. Follow the installer screens.
3. Open **Dhara** from the Desktop or Start Menu.

Uninstall keeps your data by default (`%LOCALAPPDATA%\Dhara`).

---

## Part 2 — First launch

A short splash screen starts the local database and application. There is **no**
Docker or WSL setup wizard.

When ready, the Dhara window opens on a local address such as
`http://127.0.0.1:18000` (or another port if 18000 was busy).

**If Windows asks about admin:** decline elevated mode and start Dhara normally.

**Moving from an older Docker-based Dhara Desktop:** this version uses a fresh
local database under `%LOCALAPPDATA%\Dhara\pgdata`. It does **not** import the
old Docker volume `dhara_pg_data`. Export or recreate catalogue data if you need
it. You can uninstall Docker Desktop if you only installed it for Dhara.

---

## Part 3 — First login and AI settings

1. **Sign up**, then sign in.
2. Open **Settings → LLM**.

### Recommended: cloud API key

Set Provider to **OpenAI** (or your provider), paste your API key, **Save key**.

### Optional: local Ollama (Gemma 3 1B)

The desktop installer **bundles the Ollama runtime** (not the chat model). Use **Settings → Run a local model (optional)**:

1. Open the section — Dhara starts bundled Ollama if nothing is already listening on `127.0.0.1:11434` (a system Ollama is preferred when present).
2. Confirm the ~800 MB download, then let Dhara pull **`gemma3:1b`** (needs about **1 GB free**; models go under `%LOCALAPPDATA%\Dhara\ollama`). Interrupted downloads are safe to retry — Ollama resumes.
3. Click **Use this model in the form** (fills Self-hosted + Base URL + model; does not save yet).
4. Click **Save key** in the LLM section (API key can be the dummy value `ollama`).
5. Optionally **Test connection** — the first test loads the model into RAM and can take up to a minute on CPU. The model may stay loaded for a few minutes afterward and reduce free RAM for large PDF jobs.

Ollama is **not** started with Postgres/API on every launch — only when you use this Settings flow. Quit stops a Dhara-spawned Ollama; it does not stop a system Ollama you installed yourself.

**Context length (local autofill):** Ollama’s default context window is small (often 2048–4096 tokens). Metadata autofill can fail with a clear “context length exceeded” message if the prompt is truncated. Raise context with environment variable **`OLLAMA_CONTEXT_LENGTH`** (or a Modelfile `PARAMETER num_ctx …`) before starting Ollama. Dhara talks to Ollama over **`/v1`**, which **cannot** set `num_ctx` per request.

**Compact metadata prompts:** Small self-hosted models (for example `gemma3:1b`) use a shorter autofill prompt automatically. Force that mode with **`DHARA_METADATA_COMPACT=1`** (or `true`); force the full cloud-style prompt with **`DHARA_METADATA_COMPACT=0`**.

Cloud keys remain recommended on ~8 GB PCs.

### Suggest NCO codes (bundled embeddings)

The desktop installer ships **google/embeddinggemma-300m** for occupation matching (same
semantic model as the Docker default). Weights are already on disk — Suggest NCO does
**not** download from Hugging Face at runtime. Matching runs in the local job worker; if
RAM is tight or the model folder is missing, Dhara falls back to keyword-only
(TF-IDF/fuzzy) and says so in the UI. Copy diagnostics lists whether the model folder is
present. Optional LLM chat (cloud or Ollama) only confirms a few ambiguous rows; it does
not replace the local embedding model. Builders need an accepted Hub license + `HF_TOKEN`
when running `prepare-backend.ps1`.

### If you save no key

Uploads and the pipeline still work. AI-assisted steps use heuristics and need
more manual review. Suggest NCO still runs locally (embeddings / keyword-only) without a
chat key; ambiguous rows will not get LLM confirmation.

---

## Part 4 — Everyday use

| Action | How |
|--------|-----|
| Open Dhara | Double-click the **Dhara** icon |
| Start / stop services | System tray → **Start services** / **Stop services** |
| Quit | Tray → **Quit** |
| Keep data after quit | Always — normal quit does **not** delete your database |
| Support | Tray or Settings → **Open logs folder** / **Copy diagnostics** |

---

## Where your data lives

| Location | What it stores |
|----------|----------------|
| `%LOCALAPPDATA%\Dhara\pgdata\` | PostgreSQL data directory |
| `%LOCALAPPDATA%\Dhara\object_store\` | Local file storage |
| `%LOCALAPPDATA%\Dhara\runtime.json` | Secrets (JWT, DB password, MCP token) — **not** stored inside backups |
| `%LOCALAPPDATA%\Dhara\logs\` | Application logs |
| `%LOCALAPPDATA%\Dhara\backups\` | Automatic pre-migration backups |

**Erase all local Dhara data (destructive):** stop services, quit Dhara, then
delete `%LOCALAPPDATA%\Dhara`.

---

## Updates and backups

Before a schema migration (for example after upgrading the app), Dhara:

1. Checks free disk space.
2. Creates a backup with the bundled `pg_dump` (or a copy of `pgdata` if needed).
3. Only then runs migrations.

If backup fails, Dhara **will not** migrate. Do not delete the `backups` folder.
Secrets stay in `runtime.json` and are not copied into dump files.

---

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| “Run as administrator” / database will not start | Start Dhara as a normal user |
| Port in use | Dhara should fall back automatically; if not, close the other app or reboot |
| Database will not start after a crash | Dhara clears a stale lock when safe; use **Copy diagnostics** if it still fails |
| PDF job refused (memory) | Free ~1.2 GB RAM; close browsers / local AI; try again |
| Self-hosted AI fails | Open Settings → Run a local model (starts bundled Ollama); model `gemma3:1b`; Base URL `http://127.0.0.1:11434/v1`; check `%LOCALAPPDATA%\Dhara\logs\ollama.log` |
| Local model pull interrupted | Retry — Ollama resumes; ensure ~1 GB free under `%LOCALAPPDATA%\Dhara` |
| Autofill: context length exceeded | Raise `OLLAMA_CONTEXT_LENGTH` / Modelfile `num_ctx`; keep local prompts compact (`DHARA_METADATA_COMPACT=1`) |
| Autofill JSON / empty replies on 1B | Expected to improve with schema-constrained output; still review fields; try a 3B model if quality is weak |
| Test connection slow / PDF refused after test | First load can take up to a minute; model may hold RAM for a few minutes — wait or free memory |
| Need help remotely | Tray → **Copy diagnostics** and share with support (do not share the whole `backups` folder casually) |

---

## Related docs

| Doc | Purpose |
|-----|---------|
| [Deployment overview](./overview.md) | Choose desktop vs on-prem vs cloud |
| [On-prem](./on-prem.md) | Docker Compose without the Electron installer |
| [`desktop/README.md`](../../desktop/README.md) | Developer packaging |
