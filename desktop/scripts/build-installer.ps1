<#
.SYNOPSIS
  One command to produce release\DharaSetup-<version>-x64.exe.

.DESCRIPTION
  1. fetch-win-deps.ps1      PostgreSQL + embeddable Python (+ pgvector if requested)
  2. prepare-backend.ps1     Python packages + backend sources
  3. prepare-frontend.ps1    Next static export -> resources/win-x64/frontend
  4. gates                   refuse to package an incomplete runtime (incl. pgvector)
  5. npm build + electron-builder (NSIS, per-user, data kept on uninstall by default)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1 -BuildPgVector
  powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1 -PgVectorSource C:\deps\pgvector-pg16-win.zip
#>
[CmdletBinding()]
param(
  [switch]$SkipFetch,
  [switch]$SkipBackend,
  [switch]$SkipFrontend,
  [switch]$AllowNoPgVector,
  [switch]$SkipEmbeddings,
  [switch]$SkipOllama,
  [switch]$KeepOllamaGpu,
  [switch]$BuildPgVector,
  [string]$PgVectorSource = ''
)

$ErrorActionPreference = 'Stop'
$DesktopRoot = Split-Path -Parent $PSScriptRoot
$Runtime     = Join-Path $DesktopRoot 'resources\win-x64'
$ps          = 'powershell.exe'
$psArgs      = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File')

function Invoke-Step {
  param([string]$Script, [string[]]$Extra = @())
  Write-Host ''
  Write-Host "=== $Script ===" -ForegroundColor Cyan
  & $ps @psArgs (Join-Path $PSScriptRoot $Script) @Extra
  if ($LASTEXITCODE -ne 0) { throw "$Script failed (exit $LASTEXITCODE)" }
}

# 1-3 ------------------------------------------------------------------------------------
if (-not $SkipFetch) {
  $fetchArgs = @()
  if ($BuildPgVector) { $fetchArgs += '-BuildPgVector' }
  if ($PgVectorSource) { $fetchArgs += @('-PgVectorSource', $PgVectorSource) }
  if ($SkipOllama) { $fetchArgs += '-SkipOllama' }
  if ($KeepOllamaGpu) { $fetchArgs += '-KeepOllamaGpu' }
  Invoke-Step 'fetch-win-deps.ps1' $fetchArgs
}
if (-not $SkipBackend) {
  $beArgs = @()
  if ($SkipEmbeddings) { $beArgs += '-SkipEmbeddings' }
  Invoke-Step 'prepare-backend.ps1' $beArgs
}
if (-not $SkipFrontend) { Invoke-Step 'prepare-frontend.ps1' }

# 4. gates -------------------------------------------------------------------------------
Write-Host ''
Write-Host '=== Verifying runtime payload ===' -ForegroundColor Cyan
$required = @(
  'pgsql\bin\postgres.exe', 'pgsql\bin\initdb.exe', 'pgsql\bin\pg_ctl.exe', 'pgsql\bin\pg_dump.exe',
  'pgsql\bin\pg_restore.exe', 'pgsql\bin\psql.exe', 'pgsql\bin\pg_isready.exe', 'pgsql\share\postgres.bki',
  'python\python.exe', 'python\Lib\site-packages\uvicorn',
  'backend\main.py', 'backend\alembic.ini', 'backend\migrations',
  'frontend\index.html'
)
if (-not $SkipEmbeddings) {
  $required += @(
    'models\embeddinggemma-300m\config.json',
    'models\embeddinggemma-300m\nco_index.npz',
    'models\embeddinggemma-300m\nco_index.meta.json'
  )
}
if (-not $SkipOllama) {
  $required += @('ollama\ollama.exe')
}
$missing = $required | Where-Object { -not (Test-Path (Join-Path $Runtime $_)) }
if ($missing) { throw "Runtime payload incomplete. Missing:`n  $($missing -join "`n  ")" }

$hasVector = (Test-Path (Join-Path $Runtime 'pgsql\lib\vector.dll')) -and (Test-Path (Join-Path $Runtime 'pgsql\share\extension\vector.control'))
if (-not $hasVector) {
  if ($AllowNoPgVector) {
    Write-Warning 'Packaging WITHOUT pgvector — semantic features will be unavailable in this build.'
  } else {
    throw 'pgvector is missing from the bundled PostgreSQL. Run with -BuildPgVector or -PgVectorSource <zip>, or pass -AllowNoPgVector to ship without it.'
  }
}

# Secrets / user data must never ship in the payload.
$forbidden = Get-ChildItem -Path $Runtime -Recurse -Force -File -ErrorAction SilentlyContinue |
  Where-Object { $_.Name -in @('runtime.json', '.env', '.llm_credentials_fernet_key') -and $_.FullName -notlike '*\site-packages\*' }
if ($forbidden) { throw "Forbidden files in payload: $($forbidden.FullName -join ', ')" }

# 5. build ---------------------------------------------------------------------------------
Push-Location $DesktopRoot
try {
  $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
  Write-Host ''
  Write-Host '=== npm install + build ===' -ForegroundColor Cyan
  if (Test-Path 'package-lock.json') { & $npm ci --no-audit --no-fund } else { & $npm install --no-audit --no-fund }
  if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
  & $npm run build
  if ($LASTEXITCODE -ne 0) { throw 'TypeScript build failed' }

  Write-Host ''
  Write-Host '=== electron-builder (NSIS) ===' -ForegroundColor Cyan
  $env:CSC_IDENTITY_AUTO_DISCOVERY = 'false'
  & $npm exec -- electron-builder --win nsis --x64
  if ($LASTEXITCODE -ne 0) { throw 'electron-builder failed' }
} finally {
  Pop-Location
}

$version = (Get-Content (Join-Path $DesktopRoot 'package.json') -Raw | ConvertFrom-Json).version
$artifact = Join-Path $DesktopRoot "release\DharaSetup-$version-x64.exe"
if (-not (Test-Path $artifact)) { throw "Expected installer not found: $artifact" }
$hash = (Get-FileHash -Algorithm SHA256 -Path $artifact).Hash
$mb = [math]::Round((Get-Item $artifact).Length / 1MB)
Write-Host ''
Write-Host "Installer: $artifact ($mb MB)" -ForegroundColor Green
Write-Host "SHA256   : $hash"
