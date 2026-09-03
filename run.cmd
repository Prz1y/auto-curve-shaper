@echo off
REM Auto Curve Shaper Launcher
REM Ensures the script runs with Administrator privileges

echo ============================================
echo   Auto Curve Shaper - AMD Zen 5 Optimizer
echo ============================================
echo.

REM Check for admin privileges
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Running with Administrator privileges
    echo.
    goto :run
) else (
    echo [!] Administrator privileges required!
    echo     Right-click this file and select "Run as Administrator"
    echo.
    pause
    exit /b 1
)

:run
cd /d "%~dp0"
python main.py
pause
