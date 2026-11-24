<#
.SYNOPSIS
  Builds the Next.js frontend as a static export (DHARA_DESKTOP_STATIC=1) and copies the result
  to desktop/resources/win-x64/frontend.

.DESCRIPTION
  The build runs in a scratch copy (desktop/.cache/frontend-build) so your working tree's
  node_modules and .next are left alone. The desktop API serves the exported tree via
  DHARA_STATIC_UI_ROOT, so there is no Node.js server at runtime.

  Requires frontend/next.config.mjs to switch to `output: 'export'` (+ `images.unoptimized`) when
  DHARA_DESKTOP_STATIC=1. The script fails clearly if `out/index.html` is not produced.
#>
[CmdletBinding()]
param(
  [switch]$Force,
  [switch]$ForceInstall
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$DesktopRoot = Split-Path -Parent $PSScriptRoot
$RepoRoot    = Split-Path -Parent $DesktopRoot
$FrontendSrc = Join-Path $RepoRoot 'frontend'
$Build       = Join-Path $DesktopRoot '.cache\frontend-build'
$Dest        = Join-Path $DesktopRoot 'resources\win-x64\frontend'

if (-not (Test-Path (Join-Path $FrontendSrc 'package.json'))) { throw "frontend/ not found at $FrontendSrc" }

$node = Get-Command node.exe -ErrorAction SilentlyContinue
$npm  = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) { throw 'Node.js 18+ (node + npm) is required on PATH to build the frontend.' }
$nodeMajor = [int]((& $node.Source --version).TrimStart('v').Split('.')[0])
if ($nodeMajor -lt 18) { throw "Node.js 18+ required (found $nodeMajor)." }

New-Item -ItemType Directory -Force -Path $Build | Out-Null

# --- sync sources into the scratch dir (keep its node_modules for fast rebuilds) ------
Write-Host 'Syncing frontend sources...'
$roboArgs = @($FrontendSrc, $Build, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1',
              '/XD', 'node_modules', '.next', 'out', '.git',
              '/XF', '.env', '.env.*', '*.log')
& robocopy.exe @roboArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0

# --- dependencies -------------------------------------------------------------------
$lock = Join-Path $Build 'package-lock.json'
$lockHash = if (Test-Path $lock) { (Get-FileHash -Algorithm SHA256 -Path $lock).Hash } else { (Get-FileHash -Algorithm SHA256 -Path (Join-Path $Build 'package.json')).Hash }
$stamp = Join-Path $Build 'node_modules\.deps.sha256'
$haveDeps = (Test-Path $stamp) -and ((Get-Content $stamp -Raw).Trim() -eq $lockHash)
Push-Location $Build
try {
  if ($ForceInstall -or $Force -or -not $haveDeps) {
    Write-Host 'Installing frontend dependencies...'
    if (Test-Path $lock) { & $npm.Source ci --no-audit --no-fund } else { & $npm.Source install --no-audit --no-fund }
    if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
    Set-Content -Path $stamp -Value $lockHash -Encoding ASCII
  } else {
    Write-Host 'Frontend dependencies unchanged.'
  }

  # --- static export build ----------------------------------------------------------
  foreach ($d in '.next', 'out') {
    $p = Join-Path $Build $d
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  $env:DHARA_DESKTOP_STATIC = '1'
  $env:NEXT_TELEMETRY_DISABLED = '1'
  Write-Host 'Building static export (DHARA_DESKTOP_STATIC=1)...'
  & $npm.Source run build
  if ($LASTEXITCODE -ne 0) { throw 'next build failed' }
} finally {
  Pop-Location
  Remove-Item Env:DHARA_DESKTOP_STATIC -ErrorAction SilentlyContinue
}

$out = Join-Path $Build 'out'
if (-not (Test-Path (Join-Path $out 'index.html'))) {
  throw "Static export did not produce out\index.html. Ensure frontend/next.config.mjs sets output: 'export' (and images.unoptimized, no rewrites) when DHARA_DESKTOP_STATIC=1, and that no dynamic [param] routes remain."
}

# --- publish ------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
& robocopy.exe $out $Dest /MIR /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy (publish) failed ($LASTEXITCODE)" }
$global:LASTEXITCODE = 0

$count = (Get-ChildItem -Recurse -File $Dest | Measure-Object).Count
Write-Host "Frontend ready: $count files in $Dest"
