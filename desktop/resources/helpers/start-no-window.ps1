# Start a console-subsystem process with no visible window, then exit.
# The child keeps running independently (UseShellExecute=$false, CreateNoWindow=$true).
# Stdout/stderr are not redirected here — callers must log via the app itself
# (e.g. Postgres logging_collector, or use pythonw.exe from Node instead).
#
# Args (all strings):
#   -Exe           full path to executable
#   -ArgsBase64    UTF-8 JSON array of arguments, base64-encoded
#   -Cwd           working directory (optional)
#   -EnvBase64     UTF-8 JSON object of env overrides, base64-encoded (optional)
#
# Prints a single line: OK <pid>   or   ERR <message>

param(
  [Parameter(Mandatory = $true)][string]$Exe,
  [string]$ArgsBase64 = '',
  [string]$Cwd = '',
  [string]$EnvBase64 = ''
)

$ErrorActionPreference = 'Stop'

function Decode-JsonBase64([string]$b64) {
  if ([string]::IsNullOrWhiteSpace($b64)) { return $null }
  $bytes = [Convert]::FromBase64String($b64)
  $text = [System.Text.Encoding]::UTF8.GetString($bytes)
  return $text | ConvertFrom-Json
}

function Quote-Arg([string]$s) {
  if ($null -eq $s) { return '""' }
  if ($s -notmatch '[ \t"]') { return $s }
  return '"' + ($s -replace '"', '\"') + '"'
}

try {
  if (-not (Test-Path -LiteralPath $Exe)) {
    Write-Output "ERR executable not found: $Exe"
    exit 1
  }

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $Exe
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.RedirectStandardInput = $false
  $psi.RedirectStandardOutput = $false
  $psi.RedirectStandardError = $false

  if ($Cwd -and (Test-Path -LiteralPath $Cwd)) {
    $psi.WorkingDirectory = $Cwd
  }

  $argArr = Decode-JsonBase64 $ArgsBase64
  if ($argArr) {
    $parts = @()
    foreach ($a in $argArr) { $parts += (Quote-Arg ([string]$a)) }
    $psi.Arguments = [string]::Join(' ', $parts)
  }

  $envMap = Decode-JsonBase64 $EnvBase64
  if ($envMap) {
    foreach ($p in $envMap.PSObject.Properties) {
      $name = [string]$p.Name
      $val = if ($null -eq $p.Value) { '' } else { [string]$p.Value }
      if ($psi.EnvironmentVariables.ContainsKey($name)) {
        $psi.EnvironmentVariables[$name] = $val
      } else {
        [void]$psi.EnvironmentVariables.Add($name, $val)
      }
    }
  }

  $proc = [System.Diagnostics.Process]::Start($psi)
  if (-not $proc) {
    Write-Output 'ERR Start returned null'
    exit 1
  }
  Write-Output ("OK " + $proc.Id)
  exit 0
} catch {
  Write-Output ("ERR " + $_.Exception.Message)
  exit 1
}
