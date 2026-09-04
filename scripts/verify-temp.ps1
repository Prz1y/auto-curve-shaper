# Verify Tctl telemetry: sample SMN 0x59800 via the SMU probe, write CSV.
# MUST run elevated (WinRing0 driver). The probe toolchain directory is taken
# from the CS_PROBE_DIR environment variable (or -ProbeDir). Usage:
#   powershell -File scripts\verify-temp.ps1 [-Seconds 8] [-IntervalMs 250]
param(
    [int]$Seconds = 8,
    [int]$IntervalMs = 250,
    [string]$OutFile = "",
    [string]$ProbeDir = $env:CS_PROBE_DIR
)
$ErrorActionPreference = 'Continue'
if (-not $ProbeDir) {
    Write-Error "CS_PROBE_DIR is not set - point it at the SMU probe toolchain (setx CS_PROBE_DIR `<dir`>) or pass -ProbeDir"
    exit 1
}
$dir = $ProbeDir
if (-not $OutFile) { $OutFile = Join-Path $PSScriptRoot '..\logs\verify_temp.csv' }
$outDir = Split-Path $OutFile -Parent
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
try {
    $who = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $who.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "not elevated - WinRing0 driver cannot start"
    }
} catch {
    $_ | Out-File (Join-Path $outDir 'verify_temp.err.txt') -Encoding utf8
    throw
}

"t_iso,raw_hex" | Out-File -FilePath $OutFile -Encoding utf8
$deadline = (Get-Date).AddSeconds($Seconds)
$n = 0
while ((Get-Date) -lt $deadline) {
    $line = (& (Join-Path $dir 'csprobe.exe') read 0x59800 2>$null | Select-String 'SMN ').Line
    if ($line -match 'SMN 0x[0-9A-Fa-f]+ = 0x([0-9A-Fa-f]{8})') {
        "{0},{1}" -f (Get-Date -Format o), $Matches[1] | Add-Content -Path $OutFile
        $n++
    }
    Start-Sleep -Milliseconds $IntervalMs
}
Write-Output ("samples={0} outfile={1}" -f $n, $OutFile)
