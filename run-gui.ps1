# Auto Curve Shaper GUI Launcher - PowerShell
# Ensures the script runs with Administrator privileges

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Auto Curve Shaper GUI - AMD Zen 5" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check for admin privileges
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[!] Administrator privileges required!" -ForegroundColor Red
    Write-Host "    Relaunching with elevation..." -ForegroundColor Yellow
    Write-Host ""
    
    # Relaunch as admin
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

Write-Host "[OK] Running with Administrator privileges" -ForegroundColor Green
Write-Host ""

# Change to script directory
Set-Location $PSScriptRoot

# Run the GUI
python gui.py

Write-Host ""
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
