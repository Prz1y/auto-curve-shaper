# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tctl temperature telemetry

Reads the Zen Tctl register (SMN 0x59800, bits [30:21] * 0.125 - 49 °C) through
`acsprobe read` (ZenStates-Core / WinRing0). Requires an elevated process —
without elevation the WinRing0 driver cannot start and read_tctl() raises
TemperatureError with that hint.

TemperatureSampler samples on a background thread so temperature stats can be
collected concurrently with stress workloads and frequency sampling.
"""
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from config import PROBE_EXE, TCTL_SMN_ADDR, TEMP_SAMPLE_INTERVAL

logger = logging.getLogger(__name__)

# acsprobe success line: "SMN 0x059800 = 0x693B0000 (1765474304)"
_SMN_RE = re.compile(r"=\s*0x([0-9A-Fa-f]{8})")

# Raw Tctl -> °C. Verified live on 9900X3D: idle readings in the low-50s,
# smoothly tracking load, matching HWiNFO-class tools.
_TCTL_LSB_C = 0.125
_TCTL_OFFSET_C = -49.0


class TemperatureError(RuntimeError):
    """Temperature telemetry infrastructure failed (distinct from a hot CPU)"""


@dataclass
class TempStats:
    """Aggregated temperature over one measurement window"""
    min_c: float = 0.0
    max_c: float = 0.0
    avg_c: float = 0.0
    n_samples: int = 0
    n_errors: int = 0
    started: str = ""
    ended: str = ""

    def as_dict(self) -> dict:
        return {
            'min_c': round(self.min_c, 1),
            'max_c': round(self.max_c, 1),
            'avg_c': round(self.avg_c, 1),
            'n_samples': self.n_samples,
            'n_errors': self.n_errors,
            'started': self.started,
            'ended': self.ended,
        }


def read_tctl() -> float:
    """One-shot Tctl reading in °C. Raises TemperatureError on failure."""
    if not PROBE_EXE.exists():
        raise TemperatureError("SMU probe executable not found - configure PROBE_TOOLS_DIR. Expected: " + str(PROBE_EXE))
    try:
        result = subprocess.run(
            [str(PROBE_EXE), "read", hex(TCTL_SMN_ADDR)],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except subprocess.TimeoutExpired:
        raise TemperatureError(f"SMU probe read timed out after 30s")

    out = (result.stdout or "") + (result.stderr or "")
    if "INIT-FAIL" in out:
        raise TemperatureError(
            "the SMU probe cannot start the WinRing0 kernel driver "
            "(run from an elevated process)")
    if result.returncode != 0:
        raise TemperatureError(
            f"SMU probe read failed (exit {result.returncode}): {out.strip()[:200]}")

    m = _SMN_RE.search(out)
    if not m:
        raise TemperatureError(f"cannot parse SMU probe output: {out.strip()[:200]}")

    raw = int(m.group(1), 16)
    return ((raw >> 21) & 0x3FF) * _TCTL_LSB_C + _TCTL_OFFSET_C


class TemperatureSampler:
    """Background thread collecting Tctl samples until stopped.

    Read errors are counted but tolerated (transient hiccups); a window that
    ends with zero samples raises TemperatureError from stop() — for the
    calibration pipeline temperature is load-bearing data, not decoration.
    """

    def __init__(self, interval: float = TEMP_SAMPLE_INTERVAL):
        self._interval = interval
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._samples: List[float] = []
        self._errors = 0
        self._started = ""
        self._stats: Optional[TempStats] = None

    def __enter__(self) -> "TemperatureSampler":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop(raise_on_empty=exc_type is None)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._samples.clear()
        self._errors = 0
        self._stats = None
        self._started = datetime.now().isoformat()
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="tctl-sampler")
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                temp = read_tctl()
                self._samples.append(temp)
            except TemperatureError as e:
                self._errors += 1
                if len(self._samples) == 0 and self._errors >= 3:
                    # nothing ever worked — stop burning cycles on a dead pipe
                    logger.error(f"Tctl sampling is failing persistently: {e}")
                    self._stop_evt.set()
                    break
                logger.debug(f"Tctl sample error ({self._errors}): {e}")
            self._stop_evt.wait(self._interval)

    def stop(self, raise_on_empty: bool = True) -> TempStats:
        if self._thread is None:
            # Already stopped: hand back the recorded window stats. stop() is
            # called both by the context manager (__exit__) and by callers
            # reading the stats afterwards — the second call must be a no-op,
            # not a RuntimeError (v1.5.0: every battery window crashed here).
            if self._stats is not None:
                return self._stats
            raise RuntimeError("sampler was never started")
        self._stop_evt.set()
        self._thread.join(timeout=self._interval * 4 + 15)
        self._thread = None

        stats = TempStats(
            n_samples=len(self._samples),
            n_errors=self._errors,
            started=self._started,
            ended=datetime.now().isoformat(),
        )
        if self._samples:
            stats.min_c = min(self._samples)
            stats.max_c = max(self._samples)
            stats.avg_c = sum(self._samples) / len(self._samples)
            logger.info(f"Temperature window: avg {stats.avg_c:.1f} °C, "
                        f"max {stats.max_c:.1f} °C, min {stats.min_c:.1f} °C "
                        f"({stats.n_samples} samples, {stats.n_errors} errors)")
            self._stats = stats
        elif raise_on_empty:
            raise TemperatureError(
                "no Tctl samples were collected in the window "
                f"({self._errors} read errors) — temperature telemetry is "
                "required for calibration")
        return stats
