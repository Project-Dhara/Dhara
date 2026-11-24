# Stops any Dhara-owned processes (bundled Postgres / Python API / worker / app) that run from the
# given install root. Used by the NSIS installer/uninstaller so files are not locked.
param(
    [Parameter(Mandatory = $true)][string]$Root
)

$ErrorActionPreference = 'SilentlyContinue'
$rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'

# Dhara.exe first (its Job Object then reaps most children), then anything left under the install dir.
Get-Process -Name 'Dhara' | Where-Object { $_.Path -and $_.Path.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force
Start-Sleep -Milliseconds 800

Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase) -and
    $_.Name -ne 'powershell.exe'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

exit 0
