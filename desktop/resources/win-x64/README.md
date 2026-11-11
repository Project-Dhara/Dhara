# Windows x64 bundled runtimes

Populated on a **Windows build host** (binaries are gitignored).

```
win-x64/
  pgsql/          PostgreSQL 16 + pgvector
  python/         Python 3.11 embeddable + site-packages
  node/           Node.js runtime
  backend/        Dhara backend + requirements
  frontend/       Production Next.js build
```

```powershell
.\scripts\fetch-win-deps.ps1 -PgVectorZipUrl "<url>"
.\scripts\prepare-backend.ps1
.\scripts\prepare-frontend.ps1
npm run dist:win
```
