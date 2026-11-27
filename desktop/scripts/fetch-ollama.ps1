<#
.SYNOPSIS
  Downloads a pinned Windows Ollama CLI zip into resources/win-x64/ollama.

.DESCRIPTION
  Uses the standalone GitHub artifact (ollama-windows-amd64.zip), not OllamaSetup.exe.
  By default prunes CUDA/ROCm/MLX GPU payloads after extract so the CPU desktop installer
  stays smaller; pass -KeepOllamaGpu to keep them.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\fetch-ollama.ps1
  powershell -ExecutionPolicy Bypass -File scripts\fetch-ollama.ps1 -KeepOllamaGpu -Force
#>
[CmdletBinding()]
param(
  [string]$OllamaVersion = '0.40.18',
  [string]$OllamaSha256 = 'ca97292ac1e9acc77fcf473bb2741fa6acd12e3798f261b419680068b7cc4c16',
  [switch]$KeepOllamaGpu,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$DesktopRoot = Split-Path -Parent $PSScriptRoot
$Cache       = Join-Path $DesktopRoot '.cache\downloads'
$Work        = Join-Path $DesktopRoot '.cache\work'
$Out         = Join-Path $DesktopRoot 'resources\win-x64'
$OllamaDir   = Join-Path $Out 'ollama'

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

function Find-OllamaExe {
  param([string]$Root)
  $direct = Join-Path $Root 'ollama.exe'
  if (Test-Path $direct) { return $direct }
  $hit = Get-ChildItem -Path $Root -Filter 'ollama.exe' -Recurse -File -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($hit) { return $hit.FullName }
  return $null
}

$ready = Test-Path (Join-Path $OllamaDir 'ollama.exe')
if ($Force -or -not $ready) {
  $tag = if ($OllamaVersion.StartsWith('v')) { $OllamaVersion } else { "v$OllamaVersion" }
  $zipName = 'ollama-windows-amd64.zip'
  $zip = Join-Path $Cache "ollama-$tag-$zipName"
  $url = "https://github.com/ollama/ollama/releases/download/$tag/$zipName"
  Get-Download -Url $url -Dest $zip -Sha256 $OllamaSha256

  $extract = Join-Path $Work 'ollama-extract'
  Write-Host 'Extracting Ollama…'
  Expand-Zip -Zip $zip -Dest $extract

  $exe = Find-OllamaExe -Root $extract
  if (-not $exe) { throw "ollama.exe not found in $extract" }

  # Prefer the directory that contains ollama.exe (zip root or nested).
  $srcRoot = Split-Path -Parent $exe
  if (Test-Path $OllamaDir) { Remove-Item -Recurse -Force $OllamaDir }
  New-Item -ItemType Directory -Force -Path $OllamaDir | Out-Null
  Copy-Item -Path (Join-Path $srcRoot '*') -Destination $OllamaDir -Recurse -Force
  Remove-Item -Recurse -Force $extract

  if (-not $KeepOllamaGpu) {
    # Drop large GPU runner trees; CPU inference still works via the bundled exe.
    $pruneNames = @('cuda_v11', 'cuda_v12', 'cuda_v13', 'rocm', 'mlx')
    Get-ChildItem -Path $OllamaDir -Directory -Recurse -ErrorAction SilentlyContinue |
      Where-Object { $pruneNames -contains $_.Name } |
      ForEach-Object {
        Write-Host "Pruning GPU payload $($_.FullName)"
        Remove-Item -Recurse -Force $_.FullName
      }
  }
} else {
  Write-Host 'Ollama already present (use -Force to re-download).'
}

if (-not (Test-Path (Join-Path $OllamaDir 'ollama.exe'))) {
  throw "Ollama is missing ollama.exe under $OllamaDir"
}

$verFile = Join-Path $OllamaDir 'DHARA_OLLAMA_VERSION.txt'
Set-Content -Path $verFile -Value $OllamaVersion -Encoding utf8
Write-Host "Ollama     : $OllamaVersion → $OllamaDir"
Write-Host "Done. Output: $OllamaDir"
exit 0
