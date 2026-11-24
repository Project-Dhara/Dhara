<#
.SYNOPSIS
  Builds desktop/resources/win-x64/backend and installs Python dependencies into the bundled
  embeddable Python (run fetch-win-deps.ps1 first).

.DESCRIPTION
  * Bootstraps pip into resources/win-x64/python and installs backend/requirements.txt
    (minus Linux-only uvloop, and minus the optional torch/transformers embedding stack unless
    -IncludeEmbeddings is given — the desktop runs NCO matching with TF-IDF only).
  * Copies backend/ to resources/win-x64/backend (no tests, venvs, .env, or user data folders).
  * Writes python311._pth so the bundle imports from ..\backend and Lib\site-packages.
  * Pre-compiles .pyc files (the install directory may be read-only for some users).
  * Smoke-tests the key imports.
#>
[CmdletBinding()]
param(
  [switch]$Force,
  [switch]$IncludeEmbeddings
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$DesktopRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot    = Split-Path -Parent $DesktopRoot
$BackendSrc  = Join-Path $RepoRoot 'backend'
$Out         = Join-Path $DesktopRoot 'resources\win-x64'
$PyDir       = Join-Path $Out 'python'
$PyExe       = Join-Path $PyDir 'python.exe'
$BackendOut  = Join-Path $Out 'backend'
$Cache       = Join-Path $DesktopRoot '.cache'
$GetPip      = Join-Path $Cache 'downloads\get-pip.py'

if (-not (Test-Path $PyExe)) { throw "Bundled Python not found at $PyExe. Run scripts\fetch-win-deps.ps1 first." }
if (-not (Test-Path (Join-Path $BackendSrc 'main.py'))) { throw "backend/ not found at $BackendSrc" }
New-Item -ItemType Directory -Force -Path $Cache | Out-Null

# --- python311._pth -----------------------------------------------------------
$pth = Get-ChildItem -Path $PyDir -Filter 'python*._pth' | Select-Object -First 1
if (-not $pth) { throw 'python*._pth not found in embeddable Python' }
$zipName = ($pth.BaseName -replace '\._pth$', '') + '.zip'
$pthLines = @(
  $zipName,
  '.',
  'Lib\site-packages',
  '..\backend',
  'import site'
)
Set-Content -Path $pth.FullName -Value $pthLines -Encoding ASCII
New-Item -ItemType Directory -Force -Path (Join-Path $PyDir 'Lib\site-packages') | Out-Null

# --- pip ----------------------------------------------------------------------
if (-not (Test-Path (Join-Path $PyDir 'Lib\site-packages\pip'))) {
  if (-not (Test-Path $GetPip)) { throw "get-pip.py missing at $GetPip. Run scripts\fetch-win-deps.ps1 first." }
  Write-Host 'Bootstrapping pip...'
  & $PyExe $GetPip --no-warn-script-location --disable-pip-version-check
  if ($LASTEXITCODE -ne 0) { throw 'get-pip failed' }
}

# --- requirements -------------------------------------------------------------
$reqSrc = Join-Path $BackendSrc 'requirements.txt'
$drop = @('uvloop')   # no Windows wheels; uvicorn falls back to asyncio
if (-not $IncludeEmbeddings) {
  $drop += @('torch', 'transformers', 'sentence-transformers', 'accelerate', 'huggingface-hub')
}
$dropRe = '^(' + (($drop | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')\s*([=<>!~\[;#]|$)'
$reqLines = Get-Content $reqSrc | Where-Object {
  $t = $_.Trim()
  $t -and -not $t.StartsWith('#') -and ($t -inotmatch $dropRe)
}
$reqOut = Join-Path $Cache 'requirements-desktop.txt'
Set-Content -Path $reqOut -Value $reqLines -Encoding ASCII

$reqHash = (Get-FileHash -Algorithm SHA256 -Path $reqOut).Hash
$stamp = Join-Path $PyDir '.requirements.sha256'
$installed = (Test-Path $stamp) -and ((Get-Content $stamp -Raw).Trim() -eq $reqHash)
if ($Force -or -not $installed) {
  Write-Host "Installing $($reqLines.Count) Python packages (this can take several minutes)..."
  & $PyExe -m pip install --no-warn-script-location --disable-pip-version-check --prefer-binary -r $reqOut
  if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
  Set-Content -Path $stamp -Value $reqHash -Encoding ASCII
} else {
  Write-Host 'Python packages already installed (requirements unchanged; use -Force to reinstall).'
}

# --- backend sources ----------------------------------------------------------
Write-Host 'Copying backend sources...'
$xd = @(
  '.venv', '.venv311', 'venv', '__pycache__', '.pytest_cache', 'tests', 'static', '.git',
  (Join-Path $BackendSrc 'data\object_store'),
  (Join-Path $BackendSrc 'data\pdf_jobs'),
  (Join-Path $BackendSrc 'data\pdf_uploads'),
  (Join-Path $BackendSrc 'data\excel_uploads'),
  (Join-Path $BackendSrc 'data\csv_uploads'),
  (Join-Path $BackendSrc 'data\other_uploads'),
  (Join-Path $BackendSrc 'data\pdf_extraction')
)
$xf = @('.env', '.env.*', '*.pyc', '*.pyo', 'Dockerfile', 'docker-entrypoint.sh', 'run.sh', 'pytest.ini',
        '.llm_credentials_fernet_key', '.dockerignore')
$roboArgs = @($BackendSrc, $BackendOut, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1', '/XD') + $xd + @('/XF') + $xf
& robocopy.exe @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0

# --- slim down site-packages ---------------------------------------------------
$sp = Join-Path $PyDir 'Lib\site-packages'
foreach ($rel in 'pandas\tests', 'numpy\tests', 'numpy\_core\tests', 'numpy\core\tests') {
  $p = Join-Path $sp $rel
  if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
$scripts = Join-Path $PyDir 'Scripts'
if (Test-Path $scripts) { Remove-Item -Recurse -Force $scripts }

# --- precompile ----------------------------------------------------------------
Write-Host 'Compiling .pyc files...'
& $PyExe -m compileall -q -j 0 $BackendOut
if ($LASTEXITCODE -ne 0) { Write-Warning 'compileall reported errors in backend sources' }
$global:LASTEXITCODE = 0

# --- smoke test ----------------------------------------------------------------
Write-Host 'Smoke-testing imports...'
# Scripts are written to files: Windows PowerShell 5.1 mangles embedded double quotes in `python -c`.
$smokeCore = Join-Path $Cache 'smoke-core.py'
Set-Content -Path $smokeCore -Encoding ASCII -Value @(
  'import fastapi, uvicorn, sqlalchemy, alembic, psycopg2, fitz, pandas, openpyxl, jwt, cryptography, pgvector, mcp, multipart',
  "print('core imports ok')"
)
& $PyExe $smokeCore
if ($LASTEXITCODE -ne 0) { throw 'Core Python imports failed in the bundled runtime' }

$smokeApp = Join-Path $Cache 'smoke-app.py'
Set-Content -Path $smokeApp -Encoding ASCII -Value @(
  'import main',
  'import app.workers.job_worker',
  "print('app imports ok')"
)

$env:JWT_SECRET = 'smoke-test'
$env:DATABASE_URL = 'postgresql://x:y@127.0.0.1:1/z'
$env:DHARA_DESKTOP = '1'
Push-Location $BackendOut
try {
  & $PyExe $smokeApp
  if ($LASTEXITCODE -ne 0) { Write-Warning 'Importing main / job_worker failed with dummy env (see output above). The API may still start; verify manually.' }
  & $PyExe -m alembic heads
  if ($LASTEXITCODE -ne 0) { Write-Warning 'alembic heads failed (see output above)' }
} finally {
  Pop-Location
  Remove-Item Env:JWT_SECRET, Env:DATABASE_URL, Env:DHARA_DESKTOP -ErrorAction SilentlyContinue
  $global:LASTEXITCODE = 0
}

$sizeMb = [math]::Round(((Get-ChildItem -Recurse -File $Out | Measure-Object Length -Sum).Sum) / 1MB)
Write-Host "Backend ready. win-x64 payload is currently ~$sizeMb MB."
