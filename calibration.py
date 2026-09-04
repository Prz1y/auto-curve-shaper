# SPDX-License-Identifier: GPL-3.0-or-later
"""
Phase 0: full-spectrum calibration battery

One reboot per uniform-grid offset level; within a session every window runs
at a different point of the frequency axis:

    idle   no load                          -> Min-row band (cold)
    peak   pinned 1-core busy workers       -> Max-row band (single-core boost)
    allcore y-cruncher VT3 / burn           -> High-row band (hot sustained);
             its verdict doubles as the stability gate for this offset
    mid    all-core load @ PROCTHROTTLEMAX 99 -> Mid-row band (~base clock)
    low    all-core load @ PROCTHROTTLEMAX 75 -> Low-row band

Every window records (offset, regime, freq, temp, stable, whea) — one row
feeding all three tables (F-V, F-T, V-T). Window position is persisted after
each step so a crash mid-battery resumes instead of re-running, and the
aborted window plus everything after it is credited as UNSTABLE for that
offset (a crash under the staged grid is instability evidence, not noise).

Also here: the differential attribution experiment (one row +30 per reboot,
compare against the offset-0 battery) that turns "workload name" into
"which CS row this window exercises".
"""
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional

from config import (
    ATTRIBUTION_MAP, CALIB_ALLCORE_DURATION, CALIB_IDLE_DURATION,
    CALIB_PEAK_DURATION, CALIB_RAMPUP_SECONDS, CALIB_REGIMES,
    CALIB_THROTTLED_DURATION, CS_COLS, CS_ROWS, LOGS_DIR,
)
from frequency_monitor import (
    FrequencyMeasurement, check_whea_errors, sample_frequencies,
    ycruncher_available, ycruncher_stable_from_log,
)
from temperature_monitor import TemperatureSampler
from utils import cs_set_grid
from workload import ensure_throttle_100, start_regime

logger = logging.getLogger(__name__)

REGIME_DURATIONS = {
    "idle": CALIB_IDLE_DURATION,
    "peak": CALIB_PEAK_DURATION,
    "allcore": CALIB_ALLCORE_DURATION,
    "mid": CALIB_THROTTLED_DURATION,
    "low": CALIB_THROTTLED_DURATION,
}

# Min |freq delta| vs the offset-0 battery for a regime to be attributed to
# the probed row (CS offsets move frequencies both ways; sensitivity is the
# signal, not direction)
ATTRIB_DELTA_MHZ = 100

_YC_LOAD_LOG = LOGS_DIR / "ycruncher_load.log"


def _stress_verdict(load, duration: int) -> Optional[bool]:
    """Wait out the window's stress workload and read its verdict.

    True/False from y-cruncher log parsing (or burn crash detection); None
    when the window ended without a usable verdict (killed early, no log).
    """
    proc = load.procs[0]
    deadline = time.monotonic() + duration + 15
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(1)

    exited_code = proc.poll()
    if ycruncher_available():
        if exited_code is None:
            # never self-exited at its time limit — kill it; the log may lack
            # final verdicts, so report "no usable verdict"
            logger.warning("y-cruncher did not exit at its time limit; killing")
            load.terminate()
            return None
        return ycruncher_stable_from_log(_YC_LOAD_LOG)
    # burn.exe fallback: alive at deadline = survived; early nonzero = crash
    if exited_code is None:
        return True
    if exited_code == 0:
        return None  # exited cleanly but early: it never really loaded
    return False


def run_battery(state) -> List[dict]:
    """Run the remaining battery windows for the currently staged grid.

    Persists progress after every window (state.calib_regime_index) so a
    crash resumes at the aborted window instead of re-running the session.
    """
    # PROCTHROTTLEMAX persists in the power plan across reboots; a hard crash
    # during a previous mid/low window can leave the cap behind, and every
    # window of THIS session (including idle/peak) would be measured throttled
    ensure_throttle_100()

    offset = state.calib_current_offset
    rows: List[dict] = []

    while state.calib_regime_index < len(CALIB_REGIMES):
        regime = CALIB_REGIMES[state.calib_regime_index]
        duration = REGIME_DURATIONS[regime]
        window_start = datetime.now()

        logger.info(f"=== Battery window [{regime}] at offset {offset:+d} "
                    f"(window {state.calib_regime_index + 1}/{len(CALIB_REGIMES)}) ===")

        freq: Optional[FrequencyMeasurement] = None
        stress_stable: Optional[bool] = None
        load = None
        with TemperatureSampler() as tsampler:
            try:
                if regime == "idle":
                    time.sleep(2)  # let post-boot churn settle
                    freq = sample_frequencies(duration, "idle")
                else:
                    load = start_regime(regime, duration)
                    time.sleep(CALIB_RAMPUP_SECONDS)
                    sample_secs = max(duration - CALIB_RAMPUP_SECONDS, 10)
                    freq = sample_frequencies(sample_secs, f"calib_{regime}")
                    if regime != "peak":
                        stress_stable = _stress_verdict(load, duration)
            finally:
                if load is not None:
                    load.terminate()

        temp_stats = tsampler.stop()
        post_whea = check_whea_errors(window_start)

        freq_max = freq.max_frequency if freq else 0.0
        if regime in ("allcore", "mid", "low"):
            # These windows carry the offset's stress verdict as its stability
            # gate. A missing verdict (workload killed early, no log written)
            # must fail CLOSED — an unproven level must not enter the tables
            # as stable.
            gate_ok = stress_stable is True
        else:
            gate_ok = True  # idle/peak windows have no stress workload
        stable = bool(freq_max > 0 and post_whea == 0 and gate_ok)

        row = {
            'offset': offset,
            'probe': state.attrib_probe_row,  # non-None = attribution probe data
            'regime': regime,
            'freq_max': round(freq_max, 1),
            'temp_avg': round(temp_stats.avg_c, 1),
            'temp_max': round(temp_stats.max_c, 1),
            'temp_min': round(temp_stats.min_c, 1),
            'stable': stable,
            'stress_verdict': stress_stable,
            'whea': post_whea,
            'n_temp_samples': temp_stats.n_samples,
            'timestamp': datetime.now().isoformat(),
        }
        rows.append(row)
        state.calib_rows.append(row)
        state.calib_regime_index += 1
        state.save()

        logger.info(f"[{regime}] offset {offset:+d}: freq {freq_max:.0f} MHz, "
                    f"temp max {row['temp_max']} °C, stable={stable} "
                    f"(whea={post_whea}, verdict={stress_stable})")

    return rows


def mark_crash_remaining(state, reason: str) -> int:
    """Credit every not-yet-run window of the current offset as unstable.

    Called after a reboot that interrupted a battery: Windows dying under the
    staged grid is a stability verdict for that grid.
    """
    offset = state.calib_current_offset
    marked = 0
    while state.calib_regime_index < len(CALIB_REGIMES):
        regime = CALIB_REGIMES[state.calib_regime_index]
        state.calib_rows.append({
            'offset': offset, 'probe': state.attrib_probe_row,
            'regime': regime, 'freq_max': 0.0,
            'temp_avg': 0.0, 'temp_max': 0.0, 'temp_min': 0.0,
            'stable': False, 'stress_verdict': None, 'whea': None,
            'n_temp_samples': 0, 'timestamp': datetime.now().isoformat(),
            'note': reason,
        })
        state.calib_regime_index += 1
        marked += 1
    state.save()
    if marked:
        logger.warning(f"Offset {offset:+d}: {marked} window(s) marked unstable ({reason})")
    return marked


def stage_calibration_offset(state, offset: int) -> None:
    """Stage the uniform grid for the next calibration level and persist"""
    grid = [[offset] * CS_COLS for _ in range(CS_ROWS)]
    logger.info(f"Staging calibration grid: all 15 cells = {offset:+d}")
    cs_set_grid(grid, force=True)
    state.calib_current_offset = offset
    state.calib_regime_index = 0
    state.current_grid = grid
    state.save()


def stage_attribution_grid(row: int) -> None:
    """Stage the +30 probe: all three columns of one CS row, everything else 0"""
    grid = [[0] * CS_COLS for _ in range(CS_ROWS)]
    grid[row] = [30] * CS_COLS
    logger.info(f"Staging attribution probe: row {row} ({['Min','Low','Mid','High','Max'][row]}) = +30")
    cs_set_grid(grid, force=True)


def compute_attribution(baseline_rows: List[dict], probe_rows: List[dict],
                        probe_row: int) -> Dict[str, int]:
    """Regimes sensitive to this probe row (|delta| vs offset-0 battery)"""
    base = {r['regime']: r['freq_max'] for r in baseline_rows}
    found: Dict[str, int] = {}
    for r in probe_rows:
        b = base.get(r['regime'])
        if b is None or not r.get('freq_max'):
            continue
        if abs(r['freq_max'] - b) >= ATTRIB_DELTA_MHZ:
            logger.info(f"Attribution: {r['regime']} moved {r['freq_max'] - b:+.0f} MHz "
                        f"with row {probe_row} probed -> attributed")
            found[r['regime']] = probe_row
    return found


def default_attribution() -> Dict[str, str]:
    """Copy of the built-in map for reports (regime -> row NAME)"""
    from config import ROW_NAMES
    return {k: ROW_NAMES[v] for k, v in ATTRIBUTION_MAP.items()}
