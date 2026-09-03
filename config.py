"""
Configuration for Auto Curve Shaper
"""
import os
from pathlib import Path

# Version
VERSION = "1.0.0"
RELEASE_DATE = "2026-09-03"

# Paths
BASE_DIR = Path(__file__).parent
CS_PROBE_DIR = Path(r"C:\Users\deepi\.zcode\workspace\default\cs-probe")
CSPROBE_EXE = CS_PROBE_DIR / "csprobe" / "csprobe.exe"
BURN_EXE = CS_PROBE_DIR / "burn" / "burn.exe"
CLOCKS_SAMPLE_PS1 = CS_PROBE_DIR / "clocks-sample.ps1"

# Data storage
STATE_FILE = BASE_DIR / "state.json"
RESULTS_DIR = BASE_DIR / "results"
LOGS_DIR = BASE_DIR / "logs"

# CurveShaper grid
CS_ROWS = 5  # Min, Low, Mid, High, Max
CS_COLS = 3  # 0°C, 50°C, 100°C
CS_MIN_OFFSET = -30
CS_MAX_OFFSET = 30

# Row names for readability
ROW_NAMES = ["Min", "Low", "Mid", "High", "Max"]
COL_NAMES = ["0C", "50C", "100C"]

# Optimization parameters
OPTIMIZATION_TARGET = "max_frequency"  # max_frequency | min_power | efficiency

# Safety limits
INITIAL_OFFSET = -5  # Start conservatively
MIN_SAFE_OFFSET = -30  # Maximum undervolt
STEP_SIZE = 5  # Initial step size for binary search

# Stability testing
STABILITY_TEST_DURATION = 300  # seconds (5 minutes for quick testing)
BURN_TEST_DURATION = 60  # seconds for stress test
IDLE_SAMPLE_DURATION = 30  # seconds for idle frequency sampling
LOAD_SAMPLE_DURATION = 60  # seconds for load frequency sampling

# Reboot management
MAX_REBOOT_ATTEMPTS = 100  # Maximum total reboots
REBOOT_TIMEOUT = 120  # seconds to wait after triggering reboot
POST_BOOT_DELAY = 30  # seconds to wait after boot before testing

# WHEA error detection
WHEA_CRITICAL_ID = 19  # WHEA Event ID that indicates instability

# CPU info (will be detected dynamically)
BASE_FREQUENCY = 4400  # MHz, Zen 5 base frequency
