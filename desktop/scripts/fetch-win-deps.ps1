#Requires -Version 5.1
<#
.SYNOPSIS
  Download PostgreSQL 16, Node.js, and Python 3.11 embeddable into resources/win-x64.
  Optionally stage pgvector from -PgVectorZipUrl.
#>
param(
  [string]$PostgresZipUrl = "https://get.enterprisedb.com/postgresql/postgresql-16.6-1-windows-x64-binaries.zip",
  [string]$NodeZipUrl = "https://nodejs.org/dist/v20.18.1/node-v20.18.1-win-x64.zip",
  [string]$PythonZipUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip",
  [string]$PgVectorZipUrl = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Out = Join-Path $Root "resources\win-x64"
$Cache = Join-Path $Root ".cache"
New-Item -ItemType Directory -Force -Path $Out, $Cache | Out-Null

function Download-File([string]$Url, [string]$Dest) {
  if (Test-Path $Dest) {
    Write-Host "Using cached $Dest"
    return
  }
  Write-Host "Downloading $Url"
  Invoke-WebRequest -Uri $Url -OutFile $Dest
}

function Expand-Clean([string]$Zip, [string]$Dest) {
  if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  Expand-Archive -Path $Zip -DestinationPath $Dest -Force
}

# --- PostgreSQL ---
$PgZip = Join-Path $Cache "postgresql-16-windows-x64.zip"
Download-File $PostgresZipUrl $PgZip
$PgTmp = Join-Path $Cache "pgsql-extract"
Expand-Clean $PgZip $PgTmp
$PgSource = Get-ChildItem -Path $PgTmp -Directory | Where-Object { Test-Path (Join-Path $_.FullName "bin\postgres.exe") } | Select-Object -First 1
if (-not $PgSource) {
  $nested = Join-Path $PgTmp "pgsql"
  if (Test-Path (Join-Path $nested "bin\postgres.exe")) { $PgSource = Get-Item $nested }
}
if (-not $PgSource) { throw "Could not locate postgres.exe in PostgreSQL zip" }
$PgDest = Join-Path $Out "pgsql"
if (Test-Path $PgDest) { Remove-Item -Recurse -Force $PgDest }
Copy-Item -Recurse $PgSource.FullName $PgDest
Write-Host "Postgres staged at $PgDest"

# --- pgvector ---
$LibDir = Join-Path $PgDest "lib"
$ShareExt = Join-Path $PgDest "share\extension"
New-Item -ItemType Directory -Force -Path $LibDir, $ShareExt | Out-Null
if ($PgVectorZipUrl) {
  $VecZip = Join-Path $Cache "pgvector-win.zip"
  Download-File $PgVectorZipUrl $VecZip
  $VecTmp = Join-Path $Cache "pgvector-extract"
  Expand-Clean $VecZip $VecTmp
  Get-ChildItem -Path $VecTmp -Recurse -Filter "vector.dll" | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $LibDir "vector.dll") -Force
  }
  Get-ChildItem -Path $VecTmp -Recurse -Include "vector.control","vector--*.sql" | ForEach-Object {
    Copy-Item $_.FullName $ShareExt -Force
  }
  if (-not (Test-Path (Join-Path $LibDir "vector.dll"))) {
    throw "pgvector zip did not contain vector.dll"
  }
  Write-Host "pgvector installed into pgsql lib/share"
} else {
  Write-Warning @"
PgVectorZipUrl was not set. Place Windows PG16 pgvector files manually:
  $LibDir\vector.dll
  $ShareExt\vector.control
  $ShareExt\vector--*.sql
"@
}

# --- Node.js ---
$NodeZip = Join-Path $Cache "node-win-x64.zip"
Download-File $NodeZipUrl $NodeZip
$NodeTmp = Join-Path $Cache "node-extract"
Expand-Clean $NodeZip $NodeTmp
$NodeSource = Get-ChildItem -Path $NodeTmp -Directory | Where-Object { Test-Path (Join-Path $_.FullName "node.exe") } | Select-Object -First 1
if (-not $NodeSource) { throw "node.exe not found in Node zip" }
$NodeDest = Join-Path $Out "node"
if (Test-Path $NodeDest) { Remove-Item -Recurse -Force $NodeDest }
Copy-Item -Recurse $NodeSource.FullName $NodeDest
Write-Host "Node staged at $NodeDest"

# --- Python embeddable ---
$PyZip = Join-Path $Cache "python-embed.zip"
Download-File $PythonZipUrl $PyZip
$PyDest = Join-Path $Out "python"
if (Test-Path $PyDest) { Remove-Item -Recurse -Force $PyDest }
New-Item -ItemType Directory -Force -Path $PyDest | Out-Null
Expand-Archive -Path $PyZip -DestinationPath $PyDest -Force
Get-ChildItem $PyDest -Filter "python*._pth" | ForEach-Object {
  $content = Get-Content $_.FullName
  $content = $content | ForEach-Object {
    if ($_ -match '^#\s*import site') { 'import site' } else { $_ }
  }
  if ($content -notcontains 'Lib\site-packages') {
    $content += 'Lib\site-packages'
  }
  Set-Content -Path $_.FullName -Value $content
}
Write-Host "Python embeddable staged at $PyDest"
Write-Host "Done. Next: prepare-backend.ps1 and prepare-frontend.ps1"
