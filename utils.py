# SPDX-License-Identifier: GPL-3.0-or-later
"""
Utility functions for Auto Curve Shaper
"""
import subprocess
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import time

from config import BASE_DIR, CSPROBE_EXE, LOGS_DIR, ROW_NAMES, COL_NAMES

# Setup logging
LOGS_DIR.mkdir(exist_ok=True)
log_file = LOGS_DIR / f"auto_curve_shaper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def run_command(cmd: List[str], check: bool = True, capture_output: bool = True, 
                timeout: Optional[int] = None, admin: bool = False) -> subprocess.CompletedProcess:
    """
    Run a command with optional admin privileges
    """
    logger.debug(f"Running command: {' '.join(cmd)}")
    
    if admin:
        # For admin commands on Windows, we need to use the elevated runner
        # For now, assume the script is already running as admin
        pass
    
    try:
        result = subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True,
            encoding='utf-8',
            errors='replace',  # schtasks etc. emit localized (GBK) text
            timeout=timeout
        )
        if result.stdout:
            logger.debug("Command output: %s", result.stdout[:500])
        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {e}")
        if e.stdout:
            logger.error(f"Stdout: {e.stdout}")
        if e.stderr:
            logger.error(f"Stderr: {e.stderr}")
        raise
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timeout: {e}")
        raise


def run_powershell(script_path: Path, args: List[str] = None, timeout: Optional[int] = None) -> str:
    """
    Run a PowerShell script and return output
    """
    cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
    if args:
        cmd.extend(args)
    
    result = run_command(cmd, timeout=timeout)
    return result.stdout


def run_csprobe(args: List[str], force: bool = False) -> str:
    """
    Run the SMU probe executable with given arguments
    """
    if not CSPROBE_EXE.exists():
        raise FileNotFoundError(
            "SMU probe executable not found. Set the CS_PROBE_DIR environment "
            'variable (setx CS_PROBE_DIR "<toolchain dir>") or place the '
            "toolchain in the project's probe-tools/ folder. Expected: "
            f"{CSPROBE_EXE}")
    
    cmd = [str(CSPROBE_EXE)] + args
    if force and "-f" not in args:
        cmd.append("-f")

    result = run_command(cmd, admin=True, timeout=60)
    return result.stdout


def cs_set_cell(row: int, col: int, offset: int, force: bool = True) -> None:
    """
    Set a single CurveShaper cell
    row: 0-4 (Min, Low, Mid, High, Max)
    col: 0-2 (0°C, 50°C, 100°C)
    offset: -30 to +30
    """
    if not (0 <= row < 5):
        raise ValueError(f"Invalid row {row}, must be 0-4")
    if not (0 <= col < 3):
        raise ValueError(f"Invalid col {col}, must be 0-2")
    if not (-30 <= offset <= 30):
        raise ValueError(f"Invalid offset {offset}, must be -30 to +30")
    
    logger.info(f"Setting CS cell [{ROW_NAMES[row]}, {COL_NAMES[col]}] = {offset:+d}")
    run_csprobe(["cs-set", str(row), str(col), str(offset)], force=force)


def cs_clear(force: bool = True) -> None:
    """
    Clear all CurveShaper cells (set to 0)
    """
    logger.info("Clearing all CS cells")
    run_csprobe(["cs-clear"], force=force)


def cs_set_grid(grid: List[List[int]], force: bool = True) -> None:
    """
    Set entire CurveShaper grid
    grid: 5x3 list of offsets
    """
    if len(grid) != 5 or any(len(row) != 3 for row in grid):
        raise ValueError("Grid must be 5x3")
    
    logger.info("Setting CS grid:")
    for row_idx, row in enumerate(grid):
        logger.info(f"  {ROW_NAMES[row_idx]}: {row}")
    
    # Write every cell including zeros: a skipped 0 would leave a stale test
    # value in the hardware register instead of the intended final value
    for row_idx, row in enumerate(grid):
        for col_idx, offset in enumerate(row):
            cs_set_cell(row_idx, col_idx, offset, force=force)


def get_cpu_info() -> Dict[str, Any]:
    """
    Get CPU information from csprobe
    """
    output = run_csprobe(["info"])
    # Parse output for CPU name, core count, etc.
    # For now, return basic info
    return {
        "timestamp": datetime.now().isoformat(),
        "raw_output": output
    }


def save_json(data: Dict[str, Any], file_path: Path) -> None:
    """
    Save data to JSON file
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.debug(f"Saved data to {file_path}")


def load_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Load data from JSON file
    """
    if not file_path.exists():
        return None
    
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    logger.debug(f"Loaded data from {file_path}")
    return data


def check_admin_privileges() -> bool:
    """
    Check if running with admin privileges
    """
    import ctypes
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False


def trigger_reboot(delay_seconds: int = 30) -> None:
    """
    Trigger system reboot with delay
    """
    logger.warning(f"Triggering reboot in {delay_seconds} seconds...")
    run_command(["shutdown", "/r", "/t", str(delay_seconds)], admin=True)


def cancel_reboot() -> None:
    """
    Cancel pending reboot
    """
    logger.info("Cancelling reboot")
    run_command(["shutdown", "/a"], admin=True, check=False)


# ---------------------------------------------------------------------------
# Logon auto-continue via Task Scheduler
# ---------------------------------------------------------------------------

AUTOSTART_TASK_NAME = "AutoCurveShaper-AutoContinue"


def register_autostart_task() -> bool:
    """Register a logon task that relaunches the GUI elevated with --continue.

    Task Scheduler is the only sanctioned mechanism for auto-elevating at
    logon (UAC prompts cannot be pre-answered). Must be called from an
    elevated process. Returns True on success.
    """
    launcher = BASE_DIR / "run-gui.cmd"
    if not launcher.exists():
        logger.error(f"Cannot register autostart task: {launcher} not found")
        return False

    # PowerShell ScheduledTasks API: schtasks /TR mangles embedded quotes
    # around arguments, this path keeps them intact. Register-ScheduledTask
    # errors are NON-terminating and don't set $LASTEXITCODE, so the success
    # check must be an explicit try/catch, not the process exit code.
    ps_script = (
        "try {{ "
        "$a = New-ScheduledTaskAction -Execute '{exe}' -Argument '--continue'; "
        "$t = New-ScheduledTaskTrigger -AtLogOn; "
        "$p = New-ScheduledTaskPrincipal -UserId $env:USERNAME "
        "-LogonType Interactive -RunLevel Highest; "
        "Register-ScheduledTask -TaskName '{name}' -Action $a -Trigger $t "
        "-Principal $p -Force -ErrorAction Stop | Out-Null; "
        "exit 0 "
        "}} catch {{ "
        "$_.Exception.Message | Write-Error; exit 1 "
        "}}"
    ).format(exe=str(launcher), name=AUTOSTART_TASK_NAME)

    result = run_command(
        ["powershell", "-NoProfile", "-Command", ps_script],
        check=False, timeout=60
    )
    if result.returncode == 0:
        logger.info(f"Autostart task registered: GUI will relaunch at logon "
                    f"('{AUTOSTART_TASK_NAME}')")
        return True
    logger.error(f"Failed to register autostart task: {(result.stderr or '').strip()}")
    return False


def unregister_autostart_task() -> None:
    """Remove the logon autostart task (absent task is not an error)"""
    ps_script = (
        "Unregister-ScheduledTask -TaskName '{name}' -Confirm:$false "
        "-ErrorAction SilentlyContinue"
    ).format(name=AUTOSTART_TASK_NAME)
    result = run_command(
        ["powershell", "-NoProfile", "-Command", ps_script],
        check=False, timeout=60
    )
    if result.returncode == 0:
        logger.info("Autostart task removed")
    else:
        logger.debug(f"Autostart task removal: {(result.stderr or '').strip()}")
