#Requires -Version 5.1
<#
.SYNOPSIS
  Full Windows packaging pipeline: deps → backend → frontend → electron-builder NSIS Setup.exe.
#>
param(
  [string]$PgVectorZipUrl = "",
  [switch]$SkipFetch,
  [switch]$SkipBackend,
  [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Desktop = Split-Path -Parent $PSScriptRoot
Set-Location $Desktop

function Invoke-Step([string]$Name, [scriptblock]$Block) {
  Write-Host "`n=== $Name ===" -ForegroundColor Cyan
  & $Block
}

if (-not $SkipFetch) {
  Invoke-Step "Fetch Windows runtimes" {
    & "$PSScriptRoot\fetch-win-deps.ps1" -PgVectorZipUrl $PgVectorZipUrl
  }
}
if (-not $SkipBackend) {
  Invoke-Step "Prepare backend" { & "$PSScriptRoot\prepare-backend.ps1" }
}
if (-not $SkipFrontend) {
  Invoke-Step "Prepare frontend" { & "$PSScriptRoot\prepare-frontend.ps1" }
}

$required = @(
  "resources\win-x64\pgsql\bin\postgres.exe",
  "resources\win-x64\python\python.exe",
  "resources\win-x64\node\node.exe",
  "resources\win-x64\backend\main.py",
  "resources\win-x64\frontend\.next",
  "resources\win-x64\pgsql\lib\vector.dll"
)
$missing = @()
foreach ($rel in $required) {
  if (-not (Test-Path (Join-Path $Desktop $rel))) { $missing += $rel }
}
if ($missing.Count -gt 0) {
  Write-Warning ("Missing resources:`n - " + ($missing -join "`n - "))
  if ($missing -contains "resources\win-x64\pgsql\lib\vector.dll") {
    Write-Warning "Pass -PgVectorZipUrl or copy vector.dll manually before packaging."
  }
  throw "Refusing to build installer with missing resources"
}

if (-not (Test-Path (Join-Path $Desktop "node_modules\electron"))) {
  Invoke-Step "npm install (desktop)" { npm install }
}

Invoke-Step "electron-builder (NSIS + portable)" {
  npm run dist:win
}

Write-Host "`nArtifacts under desktop\release\" -ForegroundColor Green
Get-ChildItem (Join-Path $Desktop "release") | Format-Table Name, Length, LastWriteTime
