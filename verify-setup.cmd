@echo off
REM Auto Curve Shaper - Installation Verification Script
REM Checks if all requirements are met before running

echo ============================================
echo   Auto Curve Shaper - Setup Verification
echo ============================================
echo.

REM Check Python
echo [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorLevel% == 0 (
    python --version
    echo [OK] Python found
) else (
    echo [ERROR] Python not found!
    echo Please install Python 3.8 or higher from https://www.python.org/
    pause
    exit /b 1
)
echo.

REM Check Python version
echo [2/5] Checking Python version...
python -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Python version is 3.8 or higher
) else (
    echo [WARNING] Python version might be too old (need 3.8+)
)
echo.

REM Check tkinter
echo [3/5] Checking tkinter (GUI support)...
python -c "import tkinter" >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] tkinter available
) else (
    echo [ERROR] tkinter not found - the GUI will not work
    echo Reinstall Python and enable the tcl/tk component
)
echo.

REM Check cs-probe
echo [4/5] Checking cs-probe tools...
if exist "C:\Users\deepi\.zcode\workspace\default\cs-probe\csprobe\csprobe.exe" (
    echo [OK] csprobe.exe found
) else (
    echo [WARNING] csprobe.exe not found at default location
    echo You need to configure CS_PROBE_DIR in config.py
)
echo.

REM Check admin privileges
echo [5/5] Checking administrator privileges...
net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Running with Administrator privileges
) else (
    echo [WARNING] Not running as Administrator
    echo The tool requires admin privileges to work
)
echo.

echo ============================================
echo   Setup Verification Complete
echo ============================================
echo.
echo Next steps:
echo   1. If cs-probe path is different, edit config.py
echo   2. Run with Administrator privileges:
echo      Right-click run-gui.cmd ^> Run as Administrator
echo   3. Read docs\en\QUICKSTART.md (or docs\zh\QUICKSTART.md) for usage
echo.

pause
