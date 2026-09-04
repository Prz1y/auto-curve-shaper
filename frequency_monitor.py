"""
Frequency monitoring and measurement

clocks-sample.ps1 writes per-CCX "% Processor Performance" percentages to a
CSV file (t_sec,ccx0_pct,ccx1_pct); its stdout only carries progress lines.
We therefore read the CSV and convert percentages to MHz via the CPU base
clock. Measurement infrastructure failures raise MeasurementError instead of
being mistaken for an unstable configuration.
"""
import atexit
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

from config import (
    CLOCKS_SAMPLE_PS1, BURN_EXE, BASE_FREQUENCY, WHEA_CRITICAL_ID,
    LOGS_DIR, BURN_RAMPUP_SECONDS, PS_TIMEOUT_MARGIN,
    YCRUNCHER_EXE, STRESS_TEST_NAME,
)
from utils import run_powershell, run_command

logger = logging.getLogger(__name__)


class MeasurementError(RuntimeError):
    """Frequency measurement infrastructure failed (distinct from instability)"""


@dataclass
class FrequencyMeasurement:
    """Frequency measurement result

    all_cores holds the peak frequency (MHz) of each CCX, so avg_frequency
    and max_frequency operate over per-CCX peaks.
    """
    timestamp: str
    ccd0_freq: float  # peak MHz of first CCX
    ccd1_freq: float  # peak MHz of second CCX (0.0 on single-CCX CPUs)
    all_cores: List[float]  # peak MHz per CCX
    test_type: str  # "idle" or "load"
    duration: int  # seconds

    @property
    def avg_frequency(self) -> float:
        """Average frequency across CCX peaks"""
        return sum(self.all_cores) / len(self.all_cores) if self.all_cores else 0.0

    @property
    def max_frequency(self) -> float:
        """Maximum frequency across CCX peaks"""
        return max(self.all_cores) if self.all_cores else 0.0


# ---------------------------------------------------------------------------
# Stress workload management
# Preferred backend is y-cruncher (detects computation errors); burn.exe is
# the fallback when y-cruncher is not installed (crash detection only).
# Every workload process is registered so it can be terminated on demand (GUI
# stop/exit) and via atexit, otherwise an orphaned workload keeps the CPU
# pinned at full load after the tool exits.
# ---------------------------------------------------------------------------

_active_burn: List[subprocess.Popen] = []


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def ycruncher_available() -> bool:
    return YCRUNCHER_EXE.exists()


def _spawn_ycruncher(duration: int, log_path: Path) -> subprocess.Popen:
    """Start y-cruncher with output to a file.

    stdout must be a file, not a pipe: piped output makes y-cruncher ignore
    its -TL time limit and (because of C runtime buffering) the verdict lines
    can be lost if we terminate it. A file redirect matches console behavior
    (self-exits at the time limit) and survives our termination.
    """
    if not ycruncher_available():
        raise FileNotFoundError(f"y-cruncher not found at {YCRUNCHER_EXE}")
    logger.info(f"Starting y-cruncher ({STRESS_TEST_NAME}, time limit {duration}s)...")
    fh = open(log_path, 'w', encoding='utf-8')
    proc = subprocess.Popen(
        [str(YCRUNCHER_EXE), "stress", STRESS_TEST_NAME, f"-TL:{duration}"],
        stdout=fh,
        stderr=subprocess.STDOUT,
        # y-cruncher ends with a "press any key" prompt; stdin must hit EOF
        # or the process hangs forever after finishing its work
        stdin=subprocess.DEVNULL,
        creationflags=_creation_flags()
    )
    proc._yc_log_fh = fh  # closed in _terminate_burn
    _active_burn.append(proc)
    return proc


def _spawn_burn() -> subprocess.Popen:
    if not BURN_EXE.exists():
        raise FileNotFoundError(f"burn.exe not found at {BURN_EXE}")
    logger.info("Starting burn.exe...")
    proc = subprocess.Popen(
        [str(BURN_EXE)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_creation_flags()
    )
    _active_burn.append(proc)
    return proc


def _spawn_workload(duration: int) -> subprocess.Popen:
    """Best available all-core stress workload for `duration` seconds"""
    if ycruncher_available():
        return _spawn_ycruncher(duration, LOGS_DIR / "ycruncher_load.log")
    return _spawn_burn()


def _terminate_burn(proc: subprocess.Popen) -> None:
    logger.info("Stopping stress workload...")
    fh = getattr(proc, "_yc_log_fh", None)
    if proc in _active_burn:
        _active_burn.remove(proc)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    if fh is not None:
        try:
            fh.close()
        except OSError:
            pass


def stop_all_workloads() -> None:
    """Terminate every burn.exe started by this process"""
    for proc in list(_active_burn):
        try:
            _terminate_burn(proc)
        except Exception as e:
            logger.error(f"Failed to stop burn process: {e}")


atexit.register(stop_all_workloads)


# ---------------------------------------------------------------------------
# Frequency sampling via clocks-sample.ps1
# ---------------------------------------------------------------------------

def _read_clocks_csv(csv_path: Path) -> Tuple[List[float], List[float]]:
    """
    Parse clocks-sample.ps1 output CSV: rows of "t_sec,ccx0_pct,ccx1_pct".
    Returns (ccx0 percentages, ccx1 percentages), zero values dropped
    (Get-Counter hiccups / empty CCX on single-CCX CPUs report 0).
    """
    ccx0_pcts: List[float] = []
    ccx1_pcts: List[float] = []

    with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) < 2 or parts[0].strip().lower() == 't_sec':
                continue
            try:
                c0 = float(parts[1])
                c1 = float(parts[2]) if len(parts) > 2 and parts[2].strip() else 0.0
            except ValueError:
                continue
            if c0 > 0:
                ccx0_pcts.append(c0)
            if c1 > 0:
                ccx1_pcts.append(c1)

    return ccx0_pcts, ccx1_pcts


def _pct_to_mhz(pct: float) -> float:
    return pct * BASE_FREQUENCY / 100.0


def _sample_frequencies(sample_seconds: int, test_type: str) -> FrequencyMeasurement:
    """Run clocks-sample.ps1 and reduce its CSV output to per-CCX peak MHz"""
    csv_path = LOGS_DIR / f"clocks_{test_type}.csv"
    try:
        csv_path.unlink()
    except FileNotFoundError:
        pass

    run_powershell(
        CLOCKS_SAMPLE_PS1,
        args=["-Seconds", str(sample_seconds), "-OutFile", str(csv_path)],
        timeout=sample_seconds + PS_TIMEOUT_MARGIN
    )

    if not csv_path.exists():
        raise MeasurementError(f"clocks-sample.ps1 produced no output file at {csv_path}")

    ccx0_pcts, ccx1_pcts = _read_clocks_csv(csv_path)

    def peak_mhz(pcts: List[float]) -> float:
        mhz_values = [m for m in (_pct_to_mhz(p) for p in pcts) if 400 <= m <= 10000]
        return max(mhz_values) if mhz_values else 0.0

    ccd0_freq = peak_mhz(ccx0_pcts)
    ccd1_freq = peak_mhz(ccx1_pcts)
    peaks = [p for p in (ccd0_freq, ccd1_freq) if p > 0]

    if not peaks:
        raise MeasurementError(
            f"No valid frequency samples in {csv_path} "
            f"(rows parsed: ccx0={len(ccx0_pcts)}, ccx1={len(ccx1_pcts)})"
        )

    result = FrequencyMeasurement(
        timestamp=datetime.now().isoformat(),
        ccd0_freq=ccd0_freq,
        ccd1_freq=ccd1_freq,
        all_cores=peaks,
        test_type=test_type,
        duration=sample_seconds
    )

    logger.info(f"{test_type.capitalize()} measurement ({sample_seconds}s, "
                f"{len(ccx0_pcts)} samples): CCX0 peak={ccd0_freq:.0f} MHz, "
                f"CCX1 peak={ccd1_freq:.0f} MHz, best={result.max_frequency:.0f} MHz")

    return result


def measure_frequencies_idle(duration: int = 30) -> FrequencyMeasurement:
    """
    Measure CPU frequencies at idle.
    Raises MeasurementError if sampling infrastructure fails.
    """
    logger.info(f"Measuring idle frequencies for {duration} seconds...")
    return _sample_frequencies(duration, "idle")


def measure_frequencies_load(duration: int = 60) -> FrequencyMeasurement:
    """
    Measure CPU frequencies under full load.
    Raises MeasurementError if sampling infrastructure fails.
    """
    logger.info(f"Measuring load frequencies for {duration} seconds...")

    sample_seconds = max(duration - BURN_RAMPUP_SECONDS, 10)
    workload = _spawn_workload(duration)

    try:
        # Let the workload reach full load before sampling
        time.sleep(BURN_RAMPUP_SECONDS)
        if workload.poll() is not None:
            # it never loaded the CPU — sampling now would measure idle
            # clocks and label them "load"
            raise MeasurementError(
                f"stress workload exited (code {workload.returncode}) before load sampling started")
        return _sample_frequencies(sample_seconds, "load")
    finally:
        _terminate_burn(workload)


def run_stability_test(duration: int = 300) -> bool:
    """
    Run stability test.
    Returns True if stable, False if the workload crashed or (with
    y-cruncher) detected a computation error.
    Raises MeasurementError if the workload never actually ran.
    """
    if ycruncher_available():
        return _stability_ycruncher(duration)
    return _stability_burn(duration)


def _stability_ycruncher(duration: int) -> bool:
    """Stability via y-cruncher: catches computation errors, not just crashes"""
    log_path = LOGS_DIR / "ycruncher_stability.log"
    proc = _spawn_ycruncher(duration, log_path)
    try:
        # Wait out the window; y-cruncher usually self-exits at its -TL,
        # otherwise terminate it after a small grace
        start_time = time.time()
        deadline = time.monotonic() + duration + 15
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(1)

        elapsed = time.time() - start_time
        ran_full = elapsed >= duration - 2
        text = log_path.read_text(encoding='utf-8', errors='replace') if log_path.exists() else ""

        # Per-test verdicts look like "Running VT3: Passed" (or an error
        # marker). Match verdict values only — the config line
        # "Stop on Error: Enabled" must not count as an error.
        verdicts = re.findall(r"Running\s+\S+:\s*(\S+)", text)
        failures = [v for v in verdicts if v.lower() != "passed"]
        if failures:
            logger.warning(f"Stability test FAILED: y-cruncher detected errors: {failures}")
            return False
        if "aborted due to error" in text.lower():
            logger.warning("Stability test FAILED: y-cruncher aborted on error")
            return False

        if not ran_full:
            # exited (or was killed) well before the window closed: either it
            # never loaded the CPU (infrastructure failure) or it stopped early
            if verdicts:
                logger.warning(f"Stability test FAILED: workload stopped early (verdicts: {verdicts})")
                return False
            raise MeasurementError(
                f"y-cruncher exited after ~{int(elapsed)}s "
                f"(time limit {duration}s) without completing the test window")

        # Full window survived; verdict lines may be missing if the process
        # had to be terminated, but any DETECTED error would be in the log
        logger.info("Stability test PASSED (y-cruncher: no computation errors detected)")
        return True

    finally:
        _terminate_burn(proc)


def _stability_burn(duration: int) -> bool:
    """Stability via burn.exe fallback: crash detection only"""
    logger.warning("y-cruncher not installed - falling back to burn.exe "
                   "(crash detection only, no computation error checking)")

    burn_process = _spawn_burn()
    try:
        try:
            returncode = burn_process.wait(timeout=duration)
        except subprocess.TimeoutExpired:
            # burn ran the full duration without crashing
            logger.info("Stability test PASSED (full duration)")
            return True

        # burn exited on its own before the duration: either it crashed
        # (nonzero) or it died instantly (AV block, bad binary). A zero exit
        # well before the duration means the CPU was never actually loaded —
        # treat as infrastructure failure, NOT as "stable"
        if returncode == 0:
            raise MeasurementError(
                f"burn.exe exited cleanly after far less than {duration}s "
                f"(did not actually run)")
        logger.warning(f"Stability test FAILED with return code {returncode}")
        return False

    finally:
        _terminate_burn(burn_process)


def spawn_all_core_load(duration: int) -> subprocess.Popen:
    """Public wrapper: best available all-core stress workload"""
    return _spawn_workload(duration)


def sample_frequencies(duration: int, tag: str) -> FrequencyMeasurement:
    """Public wrapper: sample per-CCX peak MHz for `duration` seconds"""
    return _sample_frequencies(duration, tag)


def ycruncher_stable_from_log(log_path: Path) -> bool:
    """Stability verdict from a (finished or killed) y-cruncher log.

    Per-test verdicts look like "Running VT3: Passed"; match verdict values
    only — the config line "Stop on Error: Enabled" must not count as an
    error. Missing log counts as failed (callers treat None-frequency windows
    separately anyway).
    """
    try:
        text = log_path.read_text(encoding='utf-8', errors='replace') if log_path.exists() else ""
    except OSError as e:
        logger.warning(f"Cannot read y-cruncher log {log_path}: {e}")
        return False
    verdicts = re.findall(r"Running\s+\S+:\s*(\S+)", text)
    failures = [v for v in verdicts if v.lower() != "passed"]
    if failures:
        return False
    if "aborted due to error" in text.lower():
        return False
    return True


def check_whea_errors(since: Optional[datetime] = None) -> int:
    """
    Check Windows Event Log for WHEA Event ID 19 errors.
    Returns the count of errors newer than `since` (default: last 10 minutes).
    Pass an explicit timestamp to avoid attributing old errors to the
    configuration currently under test.
    """
    try:
        if since is not None:
            start_time_expr = f"[datetime]'{since.strftime('%Y-%m-%dT%H:%M:%S')}'"
        else:
            start_time_expr = "(Get-Date).AddMinutes(-10)"

        cmd = [
            "powershell",
            "-Command",
            f"Get-WinEvent -FilterHashtable @{{LogName='System'; "
            f"ProviderName='Microsoft-Windows-WHEA-Logger'; ID={WHEA_CRITICAL_ID}; "
            f"StartTime={start_time_expr}}} -ErrorAction SilentlyContinue | "
            f"Measure-Object | Select-Object -ExpandProperty Count"
        ]

        result = run_command(cmd, check=False)
        count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0

        if count > 0:
            logger.warning(f"Detected {count} WHEA Event ID {WHEA_CRITICAL_ID} errors since {since or '10 minutes ago'}")

        return count

    except Exception as e:
        logger.error(f"Failed to check WHEA errors: {e}")
        return 0
