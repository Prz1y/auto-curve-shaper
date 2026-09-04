# SPDX-License-Identifier: GPL-3.0-or-later
"""
Calibration load battery: one load generator per frequency band

Regime -> mechanism (all runtime-effective, no reboot needed):
  idle    — no load; cores sink into the Min-row band
  peak    — Python busy workers pinned to fixed logical cores via
            SetThreadAffinityMask -> single-core boost territory (Max row)
  allcore — y-cruncher (or burn.exe fallback), the existing stress path
  mid     — all-core load with PROCTHROTTLEMAX=99 (boost off, ~base clock)
  low     — all-core load with PROCTHROTTLEMAX=75

PROCTHROTTLEMAX and the pinned workers only shape WHERE on the frequency axis
the window lands; row attribution always uses the regime map + measured
frequency, never the workload name (undervolt shifts frequencies upward).
"""
import atexit
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import List

from config import MID_THROTTLE_PCT, LOW_THROTTLE_PCT, PEAK_WORKER_CORES
from frequency_monitor import _spawn_workload, _terminate_burn

logger = logging.getLogger(__name__)


class WorkloadError(RuntimeError):
    """Load-generation infrastructure failed"""


# Busy worker: pins its main thread to one logical core, then burns FP ops.
# Spawned as our own child process so we hold a terminate handle (unlike
# `start /affinity`, which detaches).
_WORKER_CODE = (
    "import ctypes, sys\n"
    "k = ctypes.windll.kernel32\n"
    "k.SetThreadAffinityMask(k.GetCurrentThread(), int(sys.argv[1]))\n"
    "x = 1.0000001\n"
    "while True:\n"
    "    x = x * 1.0000001\n"
    "    if x > 10.0: x = 1.0000001\n"
)


@dataclass
class LoadHandle:
    """A running load; terminate() must always be reached (also via atexit)"""
    regime: str
    procs: List[subprocess.Popen] = field(default_factory=list)
    throttle_pct: int = 0  # nonzero = PROCTHROTTLEMAX was set for this load

    def terminate(self) -> None:
        for p in self.procs:
            try:
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait()
            except Exception as e:
                logger.error(f"Failed to stop {self.regime} load process: {e}")
        self.procs.clear()
        if self.throttle_pct:
            _restore_throttle()


_active_loads: List[LoadHandle] = []


@atexit.register
def _cleanup_loads() -> None:
    for h in list(_active_loads):
        try:
            h.terminate()
        except Exception:
            pass
    _restore_throttle()


# ---------------------------------------------------------------------------
# PROCTHROTTLEMAX throttle (Windows power plan, immediate effect, admin only)
# ---------------------------------------------------------------------------

_throttle_active_pct = 0


def set_throttle(pct: int) -> None:
    """Cap max processor state (AC). 99 = boost disabled on Ryzen, lower =
    fraction of base clock. Requires an elevated process."""
    global _throttle_active_pct
    cmd = ["powercfg", "/setacvalueindex", "SCHEME_CURRENT",
           "SUB_PROCESSOR", "PROCTHROTTLEMAX", str(pct)]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=30)
    if result.returncode != 0:
        raise WorkloadError(
            f"powercfg set {pct}% failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout or '').strip()[:200]} — "
            "is the process elevated?")
    # SCHEME_CURRENT edits need an explicit apply
    subprocess.run(["powercfg", "/setactive", "SCHEME_CURRENT"],
                   capture_output=True, text=True, timeout=30)
    _throttle_active_pct = pct
    logger.info(f"PROCTHROTTLEMAX set to {pct}%")


def _restore_throttle() -> None:
    """Return the power plan to 100%; safe to call repeatedly"""
    global _throttle_active_pct
    if _throttle_active_pct == 0:
        return
    try:
        set_throttle(100)
        logger.info("PROCTHROTTLEMAX restored to 100%")
    except Exception as e:
        logger.error(f"Failed to restore PROCTHROTTLEMAX: {e}")
    finally:
        _throttle_active_pct = 0


def ensure_throttle_100() -> None:
    """Re-assert PROCTHROTTLEMAX=100% unconditionally (battery session start).

    The cap persists in the power plan across reboots: a hard crash during a
    mid/low window leaves it behind, and the in-process _throttle_active_pct
    flag of a fresh process cannot see that residue — every later window
    (including idle/peak of re-run levels) would be measured throttled.
    """
    global _throttle_active_pct
    if _throttle_active_pct:
        _restore_throttle()
        return
    try:
        set_throttle(100)
        logger.debug("PROCTHROTTLEMAX re-asserted at 100%")
    except (WorkloadError, OSError) as e:
        logger.warning(f"Could not re-assert PROCTHROTTLEMAX=100%: {e}")


# ---------------------------------------------------------------------------
# Regime windows
# ---------------------------------------------------------------------------

def start_peak_workers(cores: List[int] = None) -> List[subprocess.Popen]:
    """Spawn pinned busy workers (single-core boost territory)"""
    procs = []
    for core in (cores or PEAK_WORKER_CORES):
        procs.append(subprocess.Popen(
            [sys.executable, "-c", _WORKER_CODE, str(1 << core)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        logger.info(f"Peak worker pinned to logical core {core}")
    time.sleep(0.5)
    for p in procs:
        if p.poll() is not None:
            for q in procs:
                q.terminate()
            raise WorkloadError("peak busy worker exited immediately")
    return procs


def start_regime(regime: str, duration: int) -> LoadHandle:
    """Start the load for a battery window; caller MUST terminate() the handle"""
    handle = LoadHandle(regime=regime)

    if regime == "idle":
        return handle

    if regime == "peak":
        handle.procs = start_peak_workers()

    elif regime == "allcore":
        handle.procs = [_spawn_workload(duration)]

    elif regime in ("mid", "low"):
        pct = MID_THROTTLE_PCT if regime == "mid" else LOW_THROTTLE_PCT
        set_throttle(pct)
        handle.throttle_pct = pct
        handle.procs = [_spawn_workload(duration)]

    else:
        raise WorkloadError(f"unknown regime {regime!r}")

    _active_loads.append(handle)
    return handle
