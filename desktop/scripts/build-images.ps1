# Build and export desktop container images into desktop/vendor/
# Run from PowerShell (Windows). Requires Docker Desktop running.
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Vendor = Join-Path $Root "desktop\vendor"
New-Item -ItemType Directory -Force -Path $Vendor | Out-Null

Write-Host "Building dhara-backend:desktop…"
docker build -t dhara-backend:desktop (Join-Path $Root "backend")
if ($LASTEXITCODE -ne 0) { throw "docker build backend failed" }

Write-Host "Building dhara-frontend:desktop…"
docker build -t dhara-frontend:desktop `
  --build-arg BACKEND_ORIGIN=http://backend:8000 `
  (Join-Path $Root "frontend")
if ($LASTEXITCODE -ne 0) { throw "docker build frontend failed" }

Write-Host "Pulling postgres/pgvector…"
docker pull pgvector/pgvector:pg16
if ($LASTEXITCODE -ne 0) { throw "docker pull pgvector failed" }

Write-Host "Saving tarballs…"
docker save dhara-backend:desktop -o (Join-Path $Vendor "dhara-backend-desktop.tar")
if ($LASTEXITCODE -ne 0) { throw "docker save backend failed" }
docker save dhara-frontend:desktop -o (Join-Path $Vendor "dhara-frontend-desktop.tar")
if ($LASTEXITCODE -ne 0) { throw "docker save frontend failed" }
docker save pgvector/pgvector:pg16 -o (Join-Path $Vendor "pgvector-pg16.tar")
if ($LASTEXITCODE -ne 0) { throw "docker save pgvector failed" }

Write-Host "Done. Place Docker Desktop + Ollama installers in $Vendor for offline setup."
