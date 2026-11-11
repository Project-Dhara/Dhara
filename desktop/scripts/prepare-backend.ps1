#Requires -Version 5.1
<#
.SYNOPSIS
  Stage Dhara backend + pip dependencies into resources/win-x64 for the Windows installer.
#>
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
$Desktop = Split-Path -Parent $PSScriptRoot
$OutBackend = Join-Path $Desktop "resources\win-x64\backend"
$PythonHome = Join-Path $Desktop "resources\win-x64\python"
$Python = Join-Path $PythonHome "python.exe"
$SrcBackend = Join-Path $RepoRoot "backend"

if (-not (Test-Path $Python)) {
  throw "Missing $Python — run fetch-win-deps.ps1 first"
}
if (-not (Test-Path $SrcBackend)) {
  throw "Backend source not found at $SrcBackend"
}

Write-Host "Copying backend sources → $OutBackend"
if (Test-Path $OutBackend) { Remove-Item -Recurse -Force $OutBackend }
New-Item -ItemType Directory -Force -Path $OutBackend | Out-Null

robocopy $SrcBackend $OutBackend /E /XD .venv .venv311 __pycache__ .pytest_cache .mypy_cache /XF *.pyc /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }

New-Item -ItemType Directory -Force -Path (Join-Path $OutBackend "data") | Out-Null

$Cache = Join-Path $Desktop ".cache"
New-Item -ItemType Directory -Force -Path $Cache | Out-Null
$GetPip = Join-Path $Cache "get-pip.py"
if (-not (Test-Path $GetPip)) {
  Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $GetPip
}

Write-Host "Bootstrapping pip into embeddable Python"
& $Python $GetPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip failed" }

Write-Host "Installing backend requirements (this can take several minutes)"
$Req = Join-Path $OutBackend "requirements.txt"
& $Python -m pip install --no-warn-script-location -r $Req
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

& $Python -c "import uvicorn, alembic, fastapi; print('backend imports ok')"
if ($LASTEXITCODE -ne 0) { throw "backend import smoke failed" }

Write-Host "Backend staged successfully"
