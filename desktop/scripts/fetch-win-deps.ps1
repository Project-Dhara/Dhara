<#
.SYNOPSIS
  Downloads the Windows runtime pieces Dhara Desktop bundles: PostgreSQL (with pg_dump etc.),
  an embeddable Python, and (optionally) pgvector.

.DESCRIPTION
  Output (git-ignored):
    desktop/resources/win-x64/pgsql     PostgreSQL 16 binaries (EnterpriseDB zip, pruned)
    desktop/resources/win-x64/python    Python embeddable distribution (pip is added by prepare-backend.ps1)
    desktop/.cache/downloads            Cached archives

  pgvector has no official Windows binaries. Provide one of:
    -PgVectorSource <zip path or URL>  zip that contains vector.dll, vector.control, vector--*.sql
    -BuildPgVector                     build from source (needs Git + Visual Studio C++ Build Tools)
  Without pgvector the app still runs, but semantic-embedding features are disabled;
  build-installer.ps1 refuses to package without it unless -AllowNoPgVector is passed.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\fetch-win-deps.ps1 -BuildPgVector
#>
[CmdletBinding()]
param(
  [string]$PgVersion = '16.6-1',
  [string]$PythonVersion = '3.11.9',
  [string]$PgSha256 = '',
  [string]$PythonSha256 = '',
  [string]$PgVectorSource = '',
  [switch]$BuildPgVector,
  [string]$PgVectorTag = 'v0.8.0',
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$DesktopRoot = Split-Path -Parent $PSScriptRoot
$Cache       = Join-Path $DesktopRoot '.cache\downloads'
$Work        = Join-Path $DesktopRoot '.cache\work'
$Out         = Join-Path $DesktopRoot 'resources\win-x64'
$PgDir       = Join-Path $Out 'pgsql'
$PyDir       = Join-Path $Out 'python'

New-Item -ItemType Directory -Force -Path $Cache, $Work, $Out | Out-Null

function Get-Download {
  param([string]$Url, [string]$Dest, [string]$Sha256)
  if (-not (Test-Path $Dest)) {
    Write-Host "Downloading $Url"
    $tmp = "$Dest.partial"
    Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing
    Move-Item -Force $tmp $Dest
  } else {
    Write-Host "Using cached $(Split-Path -Leaf $Dest)"
  }
  $hash = (Get-FileHash -Algorithm SHA256 -Path $Dest).Hash.ToLowerInvariant()
  Write-Host "  sha256 $hash"
  if ($Sha256 -and $hash -ne $Sha256.ToLowerInvariant()) {
    Remove-Item -Force $Dest
    throw "SHA256 mismatch for $Dest (expected $Sha256, got $hash). Deleted the cached file."
  }
}

function Expand-Zip {
  param([string]$Zip, [string]$Dest)
  if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
  if ($tar) {
    & $tar.Source -xf $Zip -C $Dest
    if ($LASTEXITCODE -ne 0) { throw "tar failed extracting $Zip" }
  } else {
    Expand-Archive -Path $Zip -DestinationPath $Dest -Force
  }
}

# ------------------------------------------------------------------ PostgreSQL
$pgReady = (Test-Path (Join-Path $PgDir 'share\postgres.bki')) -and (Test-Path (Join-Path $PgDir 'bin\pg_dump.exe'))
if ($Force -or -not $pgReady) {
  $pgZipName = "postgresql-$PgVersion-windows-x64-binaries.zip"
  $pgZip = Join-Path $Cache $pgZipName
  Get-Download -Url "https://get.enterprisedb.com/postgresql/$pgZipName" -Dest $pgZip -Sha256 $PgSha256

  $extract = Join-Path $Work 'pg-extract'
  Write-Host 'Extracting PostgreSQL (this takes a minute)...'
  Expand-Zip -Zip $pgZip -Dest $extract
  $src = Join-Path $extract 'pgsql'
  if (-not (Test-Path (Join-Path $src 'bin\postgres.exe'))) { throw "Unexpected PostgreSQL zip layout in $extract" }

  if (Test-Path $PgDir) { Remove-Item -Recurse -Force $PgDir }
  Move-Item -Force $src $PgDir
  Remove-Item -Recurse -Force $extract
} else {
  Write-Host 'PostgreSQL already present (use -Force to re-download).'
}

# ---------------------------------------------------------------------- Python
$pyReady = Test-Path (Join-Path $PyDir 'python.exe')
if ($Force -or -not $pyReady) {
  $pyZipName = "python-$PythonVersion-embed-amd64.zip"
  $pyZip = Join-Path $Cache $pyZipName
  Get-Download -Url "https://www.python.org/ftp/python/$PythonVersion/$pyZipName" -Dest $pyZip -Sha256 $PythonSha256
  Expand-Zip -Zip $pyZip -Dest $PyDir
} else {
  Write-Host 'Python already present (use -Force to re-download).'
}
# prepare-backend.ps1 bootstraps pip with this file.
Get-Download -Url 'https://bootstrap.pypa.io/get-pip.py' -Dest (Join-Path $Cache 'get-pip.py') -Sha256 ''

# --------------------------------------------------------------------- pgvector
$vecDll     = Join-Path $PgDir 'lib\vector.dll'
$vecControl = Join-Path $PgDir 'share\extension\vector.control'

function Install-PgVectorFromZip {
  param([string]$Zip)
  $x = Join-Path $Work 'pgvector-extract'
  Expand-Zip -Zip $Zip -Dest $x
  # conda-forge ".conda" packages are zips that wrap a pkg-*.tar.zst payload.
  $nested = Get-ChildItem -Path $x -Filter 'pkg-*.tar.zst' -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($nested) {
    $nx = Join-Path $x 'payload'
    New-Item -ItemType Directory -Force -Path $nx | Out-Null
    & tar.exe -xf $nested.FullName -C $nx
    if ($LASTEXITCODE -ne 0) { throw 'could not extract conda payload' }
  }
  $dll = Get-ChildItem -Recurse -Path $x -Filter 'vector.dll' | Select-Object -First 1
  $ctl = Get-ChildItem -Recurse -Path $x -Filter 'vector.control' | Select-Object -First 1
  $sql = Get-ChildItem -Recurse -Path $x -Filter 'vector--*.sql'
  if (-not $dll -or -not $ctl -or -not $sql) { throw 'pgvector zip must contain vector.dll, vector.control and vector--*.sql' }
  New-Item -ItemType Directory -Force -Path (Join-Path $PgDir 'lib'), (Join-Path $PgDir 'share\extension') | Out-Null
  Copy-Item -Force $dll.FullName (Join-Path $PgDir 'lib\vector.dll')
  Copy-Item -Force $ctl.FullName (Join-Path $PgDir 'share\extension\vector.control')
  $sql | ForEach-Object { Copy-Item -Force $_.FullName (Join-Path $PgDir 'share\extension') }
  Remove-Item -Recurse -Force $x
}

function Build-PgVector {
  $git = Get-Command git.exe -ErrorAction SilentlyContinue
  if (-not $git) { throw 'git is required for -BuildPgVector' }
  $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
  if (-not (Test-Path $vswhere)) { throw 'Visual Studio Build Tools (C++) not found (vswhere.exe missing)' }
  $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  if (-not $vs) { throw 'Visual Studio C++ x64 build tools not found' }
  $vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
  $srcDir = Join-Path $DesktopRoot '.cache\pgvector-src'
  if (Test-Path $srcDir) { Remove-Item -Recurse -Force $srcDir }
  & $git.Source clone --depth 1 --branch $PgVectorTag https://github.com/pgvector/pgvector.git $srcDir
  if ($LASTEXITCODE -ne 0) { throw 'git clone pgvector failed' }
  $bat = Join-Path $Work 'build-pgvector.bat'
  @(
    '@echo off',
    "call `"$vcvars`" || exit /b 1",
    "set `"PGROOT=$PgDir`"",
    "cd /d `"$srcDir`" || exit /b 1",
    'nmake /NOLOGO /F Makefile.win || exit /b 1',
    'nmake /NOLOGO /F Makefile.win install || exit /b 1'
  ) | Set-Content -Encoding ASCII $bat
  & cmd.exe /c $bat
  if ($LASTEXITCODE -ne 0) { throw 'pgvector build failed' }
}

$haveVector = (Test-Path $vecDll) -and (Test-Path $vecControl)
if ($PgVectorSource) {
  if ($PgVectorSource -match '^https?://') {
    $vz = Join-Path $Cache 'pgvector-windows.zip'
    Get-Download -Url $PgVectorSource -Dest $vz -Sha256 ''
    Install-PgVectorFromZip -Zip $vz
  } else {
    Install-PgVectorFromZip -Zip (Resolve-Path $PgVectorSource).Path
  }
} elseif ($BuildPgVector -and ($Force -or -not $haveVector)) {
  Build-PgVector
}

# ----------------------------------------------------------------------- prune
# Remove parts the app never uses (pgAdmin alone is several hundred MB).
foreach ($d in 'pgAdmin 4', 'StackBuilder', 'doc', 'symbols') {
  $p = Join-Path $PgDir $d
  if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}
$unusedBin = 'stackbuilder.exe', 'pgbench.exe', 'ecpg.exe', 'pg_regress.exe', 'pg_regress_ecpg.exe',
  'pg_isolation_regress.exe', 'isolationtester.exe', 'libpq_pipeline.exe', 'libpq_testclient.exe',
  'libpq_uri_regress.exe', 'pg_test_fsync.exe', 'pg_test_timing.exe'
foreach ($f in $unusedBin) {
  $p = Join-Path $PgDir "bin\$f"
  if (Test-Path $p) { Remove-Item -Force $p }
}
# Headers/import libs are only needed to build extensions (done above).
foreach ($d in 'include') {
  $p = Join-Path $PgDir $d
  if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}

# --------------------------------------------------------------------- verify
foreach ($f in 'bin\postgres.exe', 'bin\initdb.exe', 'bin\pg_ctl.exe', 'bin\pg_dump.exe', 'bin\pg_restore.exe',
               'bin\psql.exe', 'bin\pg_isready.exe', 'share\postgres.bki') {
  if (-not (Test-Path (Join-Path $PgDir $f))) { throw "PostgreSQL is missing $f" }
}
if (-not (Test-Path (Join-Path $PyDir 'python.exe'))) { throw 'Python is missing python.exe' }

$haveVector = (Test-Path $vecDll) -and (Test-Path $vecControl)
Write-Host ''
Write-Host "PostgreSQL : $(& (Join-Path $PgDir 'bin\postgres.exe') --version)"
Write-Host "Python     : $PythonVersion (embeddable)"
if ($haveVector) {
  Write-Host 'pgvector   : present'
} else {
  Write-Warning 'pgvector is NOT installed in the bundled PostgreSQL. Re-run with -BuildPgVector or -PgVectorSource <zip>. build-installer.ps1 will refuse to package without it unless -AllowNoPgVector.'
}
Write-Host "Done. Output: $Out"
