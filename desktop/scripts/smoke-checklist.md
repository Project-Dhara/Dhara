# Dhara Windows desktop — smoke checklist

Run on a **clean Windows 10/11 x64 VM** with no Docker/Postgres/Python preinstalled.

## Install

- [ ] Install `Dhara-Setup-*-x64.exe` (NSIS)
- [ ] Confirm Start Menu / desktop shortcut “Dhara” exists
- [ ] Launch Dhara; splash shows phases then main window
- [ ] Confirm `%LOCALAPPDATA%\Dhara\` contains `pgdata\`, `object_store\`, `logs\`, `runtime.json`

## Core app

- [ ] Login UI loads (not blank; not API JSON from :8000)
- [ ] Sign up / log in
- [ ] Dashboard loads after auth
- [ ] Settings → save an LLM API key
- [ ] Excel upload / console pipeline completes a small workbook
- [ ] PDF job: upload → extract → continue (worker + pgvector path)
- [ ] Catalogue browse works
- [ ] Uploads do not stay QUEUED forever (job_worker is running)

## Lifecycle

- [ ] Quit app; child processes exit
- [ ] Relaunch; existing DB data still present
- [ ] Second launch focuses existing window
- [ ] Uninstall keeps `%LOCALAPPDATA%\Dhara\` by default

## Website regression

- [ ] `make up` / Docker Compose website flow still works unchanged on developer machines
