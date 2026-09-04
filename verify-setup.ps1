# Auto Curve Shaper - Installation Verification Script
# Checks if all requirements are met before running

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Auto Curve Shaper - Setup Verification" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
# Note: native command failures don't throw in PowerShell, so the check
# must go through Get-Command / $LASTEXITCODE, not try/catch
Write-Host "[1/5] Checking Python installation..." -ForegroundColor Yellow
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    $pythonVersion = & python --version 2>&1
    Write-Host $pythonVersion -ForegroundColor Green
    Write-Host "[OK] Python found" -ForegroundColor Green
} else {
    Write-Host "[ERROR] Python not found!" -ForegroundColor Red
    Write-Host "Please install Python 3.8 or higher from https://www.python.org/" -ForegroundColor Red
    pause
    exit 1
}
Write-Host ""

# Check Python version
Write-Host "[2/5] Checking Python version..." -ForegroundColor Yellow
$versionCheck = python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Python version is 3.8 or higher" -ForegroundColor Green
} else {
    Write-Host "[WARNING] Python version might be too old (need 3.8+)" -ForegroundColor Yellow
}
Write-Host ""

# Check tkinter
Write-Host "[3/5] Checking tkinter (GUI support)..." -ForegroundColor Yellow
$tkinterCheck = python -c "import tkinter" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] tkinter available" -ForegroundColor Green
} else {
    Write-Host "[ERROR] tkinter not found - the GUI will not work" -ForegroundColor Red
    Write-Host "Reinstall Python and enable the tcl/tk component" -ForegroundColor Red
}
Write-Host ""

# Check SMU probe toolchain (env var CS_PROBE_DIR, else project probe-tools)
Write-Host "[4/5] Checking SMU probe toolchain..." -ForegroundColor Yellow
$probeDir = $env:CS_PROBE_DIR
if (-not $probeDir) { $probeDir = Join-Path $PSScriptRoot 'probe-tools' }
$probeExe = Join-Path $probeDir 'csprobe\csprobe.exe'
if (Test-Path $probeExe) {
    Write-Host "[OK] SMU probe executable found" -ForegroundColor Green
} else {
    Write-Host "[WARNING] SMU probe executable not found" -ForegroundColor Yellow
    Write-Host 'Set the CS_PROBE_DIR environment variable (setx CS_PROBE_DIR "dir")' -ForegroundColor Yellow
    Write-Host "or place the toolchain in the project's probe-tools\ folder" -ForegroundColor Yellow
}
Write-Host ""

# Check admin privileges
Write-Host "[5/5] Checking administrator privileges..." -ForegroundColor Yellow
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Write-Host "[OK] Running with Administrator privileges" -ForegroundColor Green
} else {
    Write-Host "[WARNING] Not running as Administrator" -ForegroundColor Yellow
    Write-Host "The tool requires admin privileges to work" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Setup Verification Complete" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor White
Write-Host "  1. If the SMU probe toolchain is elsewhere, set CS_PROBE_DIR" -ForegroundColor White
Write-Host "  2. Run with Administrator privileges:" -ForegroundColor White
Write-Host "     Right-click run-gui.cmd > Run as Administrator" -ForegroundColor White
Write-Host "  3. Read docs/en/QUICKSTART.md (or docs/zh/) for usage" -ForegroundColor White
Write-Host ""

Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
