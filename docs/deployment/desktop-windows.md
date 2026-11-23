# Dhara Desktop for Windows — setup guide

This guide explains how to run **Dhara as a local desktop app on Windows**.
You do not open the public website. Everything (database, API, UI) runs on
**your PC**, and your data stays on that PC.

If you only want Docker Compose on a server or laptop without the desktop
installer, use [On-prem deployment](./on-prem.md) instead.

---

## What you will get

| Item | Description |
|------|-------------|
| App icon | **Dhara** on the Desktop and Start Menu |
| Local stack | Postgres, API, job worker, and UI on this machine |
| Optional AI | **Ollama** (small CPU model) **or** a cloud API key in Settings |
| Persistence | Closing the app keeps your catalogue, jobs, and settings |

This is **not** a browser shortcut to [datadhara.ekstep.org](https://datadhara.ekstep.org/).

---

## Before you begin (checklist)

Confirm each item before installing:

| Check | Requirement |
|-------|-------------|
| Operating system | Windows **10 22H2 or newer** (build 19045+) or Windows **11 23H2 or newer** (build 22631+) |
| Memory | **8 GB RAM** (design target for smooth use) |
| Disk space | About **20 GB free** |
| Virtualization | Enabled in BIOS/UEFI (Intel VT-x or AMD-V) |
| Free ports | **8080**, **8000**, and **5432** not used by other software |
| Admin rights | You can approve Windows UAC prompts when asked |
| Internet (first setup) | Needed once to install Docker/Ollama and pull a small model (unless you bundle everything offline) |

**Tips for 8 GB PCs**

- Close browsers and other heavy apps during first setup.
- Do not run a large PDF job at the same moment Ollama first loads a model.

**How to check your Windows build:** press `Win + R`, type `winver`, press Enter.

---

## Choose your path

| Who you are | Start here |
|-------------|------------|
| You already have **`DharaSetup-*.exe`** | [Part 1 — Install the app](#part-1--install-the-app) |
| You only have the **source code** (no installer yet) | [Part 0 — Build the installer](#part-0--build-the-installer-developers) first, then Part 1 |
| You are a developer testing without packaging | [Appendix — Dev mode](#appendix--dev-mode-optional) |

---

## Part 0 — Build the installer (developers)

Skip this section if someone already gave you `DharaSetup-*.exe`.

### 0.1 Tools on the Windows PC

1. Install **Node.js 20 or newer** from [nodejs.org](https://nodejs.org/).
2. Install **Docker Desktop for Windows** from the official installer:  
   [Docker Desktop Installer (Windows amd64)](https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe).
3. Start **Docker Desktop** and wait until it reports that the engine is running.
4. Open a terminal in the Dhara repository root (the folder that contains `desktop/` and `backend/`).

### 0.2 Build Dhara container images

In **Git Bash**, **WSL**, or another shell that can run bash:

```bash
bash desktop/scripts/build-images.sh
```

Or from the repo root with Make:

```bash
make desktop-images
```

If bash is unavailable, run the Docker commands listed in
[`desktop/vendor/README.md`](../../desktop/vendor/README.md).

This writes image archives under `desktop/vendor/` (for example
`dhara-backend-desktop.tar`).

### 0.3 (Recommended) Bundle Docker and Ollama installers

For a smoother offline or first-run experience, download these **official**
files into `desktop/vendor/`:

| File name in `desktop/vendor/` | Download |
|--------------------------------|----------|
| `Docker Desktop Installer.exe` | [Docker Desktop for Windows](https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe) |
| `OllamaSetup.exe` | [Ollama for Windows](https://ollama.com/download/OllamaSetup.exe) |

If you skip this step, the Dhara setup wizard can download the same official
installers when needed (internet required).

### 0.4 Create `DharaSetup.exe`

```powershell
cd desktop
npm install
npm run dist
```

When it finishes, find the installer here:

```text
desktop\dist\DharaSetup-<version>-x64.exe
```

Copy that file to the PC where Dhara should be installed, then continue with
Part 1.

---

## Part 1 — Install the app

1. Double-click **`DharaSetup-*.exe`**.
2. Approve the Windows **User Account Control (UAC)** prompt if shown.
3. Follow the installer screens (accept the license, choose an install folder if asked).
4. Finish the installer. A **Dhara** shortcut is created on the Desktop and in the Start Menu.
5. Leave **Run Dhara** checked if offered, or open **Dhara** from the Desktop.

---

## Part 2 — First-run setup wizard

The first launch opens a **setup wizard** (not the main app yet). The main UI
opens only after services are healthy.

### 2.1 Choose how AI assist will work

| Option | When to choose it |
|--------|-------------------|
| **Local CPU model (Ollama)** | Recommended on 8 GB PCs. Installs Ollama and a small model. Works offline after the first download. |
| **Cloud API key later** | Skip Ollama now. Paste an OpenAI (or compatible) key later in **Settings**. |

Click **Start setup**.

### 2.2 What the wizard does automatically

In order, the wizard will:

1. Check Windows version, RAM, disk, virtualization, and free ports.
2. Configure WSL memory limits suitable for 8 GB machines.
3. Enable **WSL2** if needed.
4. Install and start **Docker Desktop** if needed.
5. If you chose local AI: install **Ollama**, start it, and pull the default small model (`qwen2.5:1.5b-instruct`).
6. Create secrets under `%LOCALAPPDATA%\Dhara\`.
7. Load Dhara container images and start **postgres**, **backend**, **worker**, and **frontend**.
8. Wait until health checks pass (`/api/ready`, worker running, UI on port 8080).

### 2.3 If Windows asks to reboot

1. Read the on-screen message.
2. Allow the reboot.
3. After login, **Dhara Setup resumes automatically** (or open **Dhara** again if it does not).
4. Do not cancel mid-setup unless you intend to retry from the beginning.

### 2.4 When setup succeeds

You should see a ready state, then the Dhara application window (local UI at
`http://127.0.0.1:8080` inside the app).

If setup fails, use **Retry**, fix the issue described on screen (for example a
busy port or disabled virtualization), and run the wizard again.

---

## Part 3 — First login and AI settings

1. Create an account with **Sign up** (enabled by default on desktop).
2. Sign in.
3. Open **Settings → LLM**.

### If you chose local Ollama

Set:

| Field | Value |
|-------|--------|
| Provider | **Self-hosted** |
| Base URL | `http://host.docker.internal:11434/v1` |
| Model | `qwen2.5:1.5b-instruct` |
| API key | `ollama` (any non-empty value is fine) |

Click **Save key**.

Desktop setup also writes `LLM_BASE_URL` and `LLM_MODEL` into
`%LOCALAPPDATA%\Dhara\.env` when local AI was selected; Settings should match
those values.

### If you chose cloud later

Set Provider to **OpenAI** (or your provider), paste your API key, and
**Save key**.

### If you save no key

Uploads and the pipeline still work. AI-assisted steps use heuristics and need
more manual review.

---

## Part 4 — Everyday use

| Action | How |
|--------|-----|
| Open Dhara | Double-click the **Dhara** icon |
| Start / stop services | System tray → **Start services** / **Stop services** |
| Quit | Tray → **Quit** |
| Keep data after quit | Always — normal quit does **not** delete your database |

Your catalogue, jobs, users, and Settings remain on this PC across restarts.

Use the same product flows as the web app: Excel / PDF / SQL → review →
catalogue → API / MCP, all locally.

---

## Where your data lives

| Location | What it stores |
|----------|----------------|
| `%LOCALAPPDATA%\Dhara\.env` | App secrets and desktop LLM defaults |
| `%LOCALAPPDATA%\Dhara\setup-state.json` | Setup progress / resume flags |
| `%LOCALAPPDATA%\Dhara\compose\` | Packaged Compose files used at runtime |
| Docker volume `dhara_pg_data` | Catalogue, jobs, users, encrypted LLM credentials |

**Stop services but keep data:** tray → **Stop services**.

**Erase all local Dhara data (destructive):**

1. Stop services.
2. In a terminal (with Docker running): remove the stack with volumes, for example from `%LOCALAPPDATA%\Dhara\compose`:

   ```powershell
   docker compose -f docker-compose.desktop.yml down -v
   ```

3. Delete the folder `%LOCALAPPDATA%\Dhara` if you also want config removed.

Uninstalling the app defaults to **keeping** data unless you choose otherwise.

---

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| “Virtualization disabled” | Enable VT-x / AMD-V in BIOS/UEFI, reboot, run setup again |
| Port already in use | Stop IIS, Skype legacy, local Postgres, or other apps using 8080 / 8000 / 5432 |
| Docker never becomes ready | Open **Docker Desktop** manually, wait for “Engine running”, click **Retry** in Dhara Setup |
| Setup did not resume after reboot | Open **Dhara** from the Start Menu; the wizard should continue |
| App opens but uploads stay “queued” | Worker must be running — use tray **Start services**, or re-run setup; `/api/ready` alone is not enough |
| Very slow or out-of-memory on 8 GB | Close other apps; avoid large PDF batches while the local model is loading |
| Self-hosted AI fails | Confirm Ollama is running (`http://127.0.0.1:11434`), model is pulled, and Settings Base URL / model / key match Part 3 |

Official documentation (only if you need vendor help):

- [Install Docker Desktop on Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
- [Ollama download](https://ollama.com/download/OllamaSetup.exe)

---

## Appendix — Dev mode (optional)

For developers iterating on the Electron shell without building an installer:

```powershell
cd desktop
npm install
npm start
```

You still need Docker images tagged for desktop (Part 0.2) and a working Docker
engine. Prefer `npm run dist` and Part 1 for a user-like install.

---

## Related docs

| Doc | Purpose |
|-----|---------|
| [Deployment overview](./overview.md) | Choose desktop vs on-prem vs cloud |
| [On-prem](./on-prem.md) | Docker Compose without the Electron installer |
| [Configuration](./configuration.md) | Environment variables (`LLM_BASE_URL`, `JWT_SECRET`, …) |
| [`desktop/README.md`](../../desktop/README.md) | Desktop package layout |
| [`desktop/vendor/README.md`](../../desktop/vendor/README.md) | Offline installer and image payloads |
