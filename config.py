# SPDX-License-Identifier: GPL-3.0-or-later
"""
Configuration for Auto Curve Shaper
"""
import os
from pathlib import Path

# Version
VERSION = "1.5.0"
RELEASE_DATE = "2026-09-04"

# Paths
BASE_DIR = Path(__file__).parent
# External SMU probe toolchain (CurveShaper writes + SMN reads) — NOT bundled
# with this repository. Resolution order:
#   1. CS_PROBE_DIR environment variable (recommended, machine-wide):
#        setx CS_PROBE_DIR "D:\path\to\probe-tools"
#   2. a project-local .\probe-tools folder
# Never commit a personal absolute path here.
# Expected layout: <dir>\csprobe\<probe>.exe, <dir>\burn\, <dir>\clocks-sample.ps1
CS_PROBE_DIR = Path(os.environ.get("CS_PROBE_DIR") or BASE_DIR / "probe-tools")
CSPROBE_EXE = CS_PROBE_DIR / "csprobe" / "csprobe.exe"
BURN_EXE = CS_PROBE_DIR / "burn" / "burn.exe"
CLOCKS_SAMPLE_PS1 = CS_PROBE_DIR / "clocks-sample.ps1"

# Stress test: y-cruncher (detects computation errors, unlike burn.exe which
# only measures crashes). Get it from https://www.numberworld.org/y-cruncher/
# and unpack so that this path exists; without it the tool falls back to
# burn.exe (crash-only detection).
YCRUNCHER_DIR = BASE_DIR / "y-cruncher"
YCRUNCHER_EXE = YCRUNCHER_DIR / "y-cruncher.exe"
STRESS_TEST_NAME = "VT3"  # AVX-512 vector transform, best Zen stability coverage

# Data storage
STATE_FILE = BASE_DIR / "state.json"
RESULTS_DIR = BASE_DIR / "results"
LOGS_DIR = BASE_DIR / "logs"

# CurveShaper grid
CS_ROWS = 5  # Min, Low, Mid, High, Max
CS_COLS = 3  # three temperature anchor columns (indices only)
CS_MIN_OFFSET = -30
CS_MAX_OFFSET = 30

# Row names for readability
ROW_NAMES = ["Min", "Low", "Mid", "High", "Max"]
# Temperature anchors per SkatterBencher's Curve Shaper measurements (-5/50/90°C).
# The hardware interface only takes column indices 0/1/2; these labels are display-only.
COL_NAMES = ["-5C", "50C", "90C"]

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
BURN_RAMPUP_SECONDS = 5  # seconds to let the stress workload reach full load before sampling
PS_TIMEOUT_MARGIN = 60  # extra seconds beyond sample duration for PowerShell startup/teardown

# Reboot management
# 15 cells × 3-7 reboots per sweep × up to MAX_SWEEPS sweeps + baseline + final
# validation + margin. Convergence usually stops the search earlier.
MAX_REBOOT_ATTEMPTS = 350  # Maximum total reboots
# CurveShaper cells interact (shaper fields overlap), so after the first full
# pass the grid is re-swept: each cell is re-searched, seeded from its previous
# optimum, until a full sweep changes nothing. Set to 1 to disable refinement
# sweeps (v1.1 behavior).
MAX_SWEEPS = 3

# Auto-continue: while an optimization run spans reboots, a scheduled task
# relaunches the GUI at logon (with --continue) elevated via Task Scheduler —
# the only sanctioned way to auto-elevate, since UAC prompts cannot be
# pre-answered. The task is removed when the run ends.
AUTO_CONTINUE_DELAY = 10  # countdown before auto-resuming (abort window)

# Auto-reboot: after each test iteration the machine reboots by itself, making
# the whole run unattended (auto-continue then resumes it at next logon).
# Each reboot has a cancelable countdown — use it when you're at the machine
# and need to save something first.
AUTO_REBOOT = True
AUTO_REBOOT_DELAY = 60  # countdown seconds before each automatic reboot
REBOOT_TIMEOUT = 120  # seconds to wait after triggering reboot
POST_BOOT_DELAY = 30  # seconds to wait after boot before testing

# WHEA error detection
WHEA_CRITICAL_ID = 19  # WHEA Event ID that indicates instability

# CPU info
BASE_FREQUENCY = 4400  # MHz; reference clock for % Processor Performance -> MHz conversion (9900X3D base)

# ---------------------------------------------------------------------------
# v1.5 calibration pipeline: model-first flow
#   Phase 0  calibrate  — uniform-grid offset sweep; each reboot measures the
#             full spectrum battery (idle/peak/allcore/mid/low), collecting the
#             frequency-voltage, frequency-temperature and voltage-temperature
#             tables as (offset, regime) -> (freq, temp, stable) data points
#   Phase 1  derive     — per-regime stability boundaries + user caps
#             (max temp / max freq / max voltage) -> derived 5x3 grid
#   Phase 2  refine     — existing multi-sweep engine as residual correction
# ---------------------------------------------------------------------------
TCTL_SMN_ADDR = 0x59800          # Zen Tctl register (bits [30:21] * 0.125 - 49 °C)
TEMP_SAMPLE_INTERVAL = 0.5       # seconds between Tctl samples during a window

# Uniform offset levels applied to ALL 15 cells, one reboot per level. 0 first
# (serves as the baseline battery), deepest last.
CALIB_OFFSETS = [0, -5, -10, -15, -20, -25, -30]

# Spectrum battery: one window per frequency band per reboot session.
# idle  — no load                -> Min row band (cold boost)
# peak  — pinned 1-core workers  -> Max row band (single-core boost)
# allcore — y-cruncher/burn all-core -> High row band (sustained hot load);
#          its y-cruncher verdict doubles as the stability gate for the offset
# mid   — all-core load capped at MID_THROTTLE_PCT (boost off, ~base clock)
# low   — all-core load capped at LOW_THROTTLE_PCT (~75% of base)
CALIB_REGIMES = ["idle", "peak", "allcore", "mid", "low"]
CALIB_IDLE_DURATION = 30
CALIB_PEAK_DURATION = 90
CALIB_ALLCORE_DURATION = 180
CALIB_THROTTLED_DURATION = 90
CALIB_RAMPUP_SECONDS = 5

MID_THROTTLE_PCT = 99   # 99% max processor state = boost disabled on Ryzen
LOW_THROTTLE_PCT = 75

# Logical cores pinned by the "peak" regime's busy workers (single-core boost
# territory; 0 = first logical CPU). Add a second core (e.g. [0, 8]) to load
# one core per CCD simultaneously.
PEAK_WORKER_CORES = [0]

# Regime -> CS row attribution. From cs-probe Test A differential experiment
# (Min row +30 moved idle clocks; High/Max +30 moved hot all-core clocks) and
# the boost-frequency ladder. Rerun the attribution experiment to override.
ATTRIBUTION_MAP = {"idle": 0, "low": 1, "mid": 2, "allcore": 3, "peak": 4}
# Rows probed (one +30 probe per reboot) by the attribution experiment
ATTRIB_PROBE_ROWS = [0, 1, 2, 3, 4]

# A throttled regime counts as "effective" only if its measured frequency came
# in clearly below the all-core window's; otherwise Mid/Low rows fall back to
# the all-core boundary (conservative).
REGIME_EFFECTIVE_DELTA_MHZ = 150

# Derivation
CALIB_MARGIN = 10               # offset units backed off from the boundary (2 steps)
MAX_TEMP_LIMIT = 90             # °C cap (user-settable in GUI)
MAX_FREQ_LIMIT = 0              # MHz cap; 0 = no cap
MAX_VOLTAGE_OFFSET = 0          # upper clamp on derived offsets (no positive voltage)
