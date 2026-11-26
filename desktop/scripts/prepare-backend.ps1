<#
.SYNOPSIS
  Builds desktop/resources/win-x64/backend and installs Python dependencies into the bundled
  embeddable Python (run fetch-win-deps.ps1 first).

.DESCRIPTION
  * Bootstraps pip into resources/win-x64/python and installs backend/requirements.txt
    (minus Linux-only uvloop). By default also installs the CPU torch + sentence-transformers
    stack and bundles google/embeddinggemma-300m under win-x64/models for offline NCO matching.
  * EmbeddingGemma is gated: set HF_TOKEN (or HUGGING_FACE_HUB_TOKEN) before prepare-backend.
  * Pass -SkipEmbeddings for a lean TF-IDF-only build (no torch, no model folder).
  * Copies backend/ to resources/win-x64/backend and pre-compiles .pyc files.
#>
[CmdletBinding()]
param(
  [switch]$Force,
  [switch]$SkipEmbeddings
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
$ModelsDir   = Join-Path $Out 'models\embeddinggemma-300m'
$BundleScript = Join-Path $PSScriptRoot 'bundle_nco_embedding_model.py'
$TorchCpuIndex = 'https://download.pytorch.org/whl/cpu'
$LegacyBgeDir = Join-Path $Out 'models\bge-small-en-v1.5'

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
# Always drop Linux-only uvloop. accelerate is optional and unused by our load path.
$drop = @('uvloop', 'accelerate')
if ($SkipEmbeddings) {
  $drop += @('torch', 'transformers', 'sentence-transformers', 'huggingface-hub')
}
$dropRe = '^(' + (($drop | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')\s*([=<>!~\[;#]|$)'
$reqLines = Get-Content $reqSrc | Where-Object {
  $t = $_.Trim()
  $t -and -not $t.StartsWith('#') -and ($t -inotmatch $dropRe)
}
# Torch must come from the CPU wheel index on Windows desktop builds.
$torchLine = $null
$otherLines = New-Object System.Collections.Generic.List[string]
foreach ($line in $reqLines) {
  if ($line -match '^torch\s*([=<>!~]|$)') { $torchLine = $line }
  else { [void]$otherLines.Add($line) }
}
$reqOut = Join-Path $Cache 'requirements-desktop.txt'
Set-Content -Path $reqOut -Value $otherLines -Encoding ASCII

$reqHashParts = @((Get-FileHash -Algorithm SHA256 -Path $reqOut).Hash)
if ($torchLine) { $reqHashParts += "torch-cpu:$torchLine" }
if ($SkipEmbeddings) { $reqHashParts += 'skip-embeddings' } else { $reqHashParts += 'with-embeddings' }
$reqHash = ($reqHashParts -join '|')
$stamp = Join-Path $PyDir '.requirements.sha256'
$installed = (Test-Path $stamp) -and ((Get-Content $stamp -Raw).Trim() -eq $reqHash)
if ($Force -or -not $installed) {
  if ($torchLine -and -not $SkipEmbeddings) {
    Write-Host "Installing CPU torch first ($torchLine)..."
    & $PyExe -m pip install --no-warn-script-location --disable-pip-version-check --prefer-binary `
      --index-url $TorchCpuIndex $torchLine
    if ($LASTEXITCODE -ne 0) { throw 'CPU torch install failed' }
  }
  Write-Host "Installing $($otherLines.Count) Python packages (this can take several minutes)..."
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

# --- EmbeddingGemma model bundle ----------------------------------------------
$modelsRoot = Join-Path $Out 'models'
if (Test-Path $LegacyBgeDir) {
  Write-Host 'Removing legacy BGE model folder (replaced by EmbeddingGemma)...'
  Remove-Item -Recurse -Force $LegacyBgeDir
}
if ($SkipEmbeddings) {
  Write-Host 'SkipEmbeddings: removing bundled NCO embedding model (if present)...'
  if (Test-Path $modelsRoot) { Remove-Item -Recurse -Force $modelsRoot }
  # Marker so Electron can leave NCO_EMBEDDING_MODEL empty.
  New-Item -ItemType Directory -Force -Path $modelsRoot | Out-Null
  Set-Content -Path (Join-Path $modelsRoot '.skip-embeddings') -Value '1' -Encoding ASCII
} else {
  $hfToken = $env:HF_TOKEN
  if (-not $hfToken) { $hfToken = $env:HUGGING_FACE_HUB_TOKEN }
  if (-not $hfToken) {
    throw 'HF_TOKEN (or HUGGING_FACE_HUB_TOKEN) is required to download gated google/embeddinggemma-300m. Accept the license on Hugging Face, then set the token and re-run prepare-backend.'
  }
  if (-not (Test-Path $BundleScript)) { throw "Missing $BundleScript" }
  Write-Host 'Bundling google/embeddinggemma-300m (download once, verify SHA-256, smoke + NCO index)...'
  $writeManifest = @()
  if (-not (Test-Path (Join-Path $PSScriptRoot 'embeddinggemma-300m.manifest.json'))) {
    $writeManifest = @('--write-manifest')
  }
  & $PyExe $BundleScript --out $ModelsDir --cache (Join-Path $Cache 'models') @writeManifest
  if ($LASTEXITCODE -ne 0) { throw 'bundle_nco_embedding_model.py failed' }
  if (Test-Path (Join-Path $modelsRoot '.skip-embeddings')) {
    Remove-Item -Force (Join-Path $modelsRoot '.skip-embeddings')
  }
}

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
$smokeCore = Join-Path $Cache 'smoke-core.py'
Set-Content -Path $smokeCore -Encoding ASCII -Value @(
  'import fastapi, uvicorn, sqlalchemy, alembic, psycopg2, fitz, pandas, openpyxl, jwt, cryptography, pgvector, mcp, multipart',
  "print('core imports ok')"
)
& $PyExe $smokeCore
if ($LASTEXITCODE -ne 0) { throw 'Core Python imports failed in the bundled runtime' }

if (-not $SkipEmbeddings) {
  $smokeEmb = Join-Path $Cache 'smoke-embeddings.py'
  Set-Content -Path $smokeEmb -Encoding ASCII -Value @(
    'import torch, transformers, sentence_transformers, huggingface_hub',
    "print('embedding imports ok', torch.__version__)"
  )
  & $PyExe $smokeEmb
  if ($LASTEXITCODE -ne 0) { throw 'Embedding stack imports failed in the bundled runtime' }
  # Offline re-smoke against the bundled folder (network blocked via env).
  $env:HF_HUB_OFFLINE = '1'
  $env:TRANSFORMERS_OFFLINE = '1'
  & $PyExe $BundleScript --out $ModelsDir --smoke-only
  if ($LASTEXITCODE -ne 0) { throw 'Offline BGE smoke encode failed' }
  Remove-Item Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue
}

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
if ($SkipEmbeddings) {
  Write-Host 'NCO embeddings: skipped (TF-IDF only).'
} else {
  Write-Host "NCO embeddings: EmbeddingGemma bundled at $ModelsDir"
}
