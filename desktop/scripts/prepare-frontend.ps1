#Requires -Version 5.1
<#
.SYNOPSIS
  Build the Next.js frontend for production and stage it under resources/win-x64/frontend.
#>
param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
$Desktop = Split-Path -Parent $PSScriptRoot
$OutFrontend = Join-Path $Desktop "resources\win-x64\frontend"
$NodeHome = Join-Path $Desktop "resources\win-x64\node"
$Node = Join-Path $NodeHome "node.exe"
$NpmCmd = Join-Path $NodeHome "npm.cmd"
$SrcFrontend = Join-Path $RepoRoot "frontend"
$Staging = Join-Path $Desktop ".cache\frontend-build"

if (-not (Test-Path $Node)) { throw "Missing $Node — run fetch-win-deps.ps1 first" }
if (-not (Test-Path $SrcFrontend)) { throw "Frontend source not found at $SrcFrontend" }

Write-Host "Staging frontend sources for production build"
if (Test-Path $Staging) { Remove-Item -Recurse -Force $Staging }
New-Item -ItemType Directory -Force -Path $Staging | Out-Null
robocopy $SrcFrontend $Staging /E /XD node_modules .next /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with code $LASTEXITCODE" }

$env:Path = "$NodeHome;$env:Path"
Push-Location $Staging
try {
  $env:BACKEND_ORIGIN = "http://127.0.0.1:18000"
  Write-Host "npm ci"
  & $NpmCmd ci
  if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
  Write-Host "npm run build"
  & $NpmCmd run build
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
  Pop-Location
}

Write-Host "Copying production frontend → $OutFrontend"
if (Test-Path $OutFrontend) { Remove-Item -Recurse -Force $OutFrontend }
New-Item -ItemType Directory -Force -Path $OutFrontend | Out-Null
robocopy $Staging $OutFrontend /E /XD .cache /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy to out failed with code $LASTEXITCODE" }

if (-not (Test-Path (Join-Path $OutFrontend ".next"))) {
  throw "Frontend build missing .next output"
}
Write-Host "Frontend staged successfully"
