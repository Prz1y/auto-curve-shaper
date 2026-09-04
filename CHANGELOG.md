# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Calibration battery crashed at the end of every window** (blocking the
  whole `calibrate` pipeline on real hardware): `TemperatureSampler.stop()`
  was called twice — by the context-manager exit and explicitly in
  `run_battery` — so the second call raised `RuntimeError("sampler was never
  started")` after each 30–180 s window and no data ever reached state.json.
  `stop()` is now idempotent and returns the recorded window stats.
  Regression-pinned in `tests/test_regressions.py`.
- **`attribute + calibrate` interleaved with the classic per-cell search**:
  after a probe battery `run()` fell through into the classic loop (no mode
  gate), whose cell writes landed on top of the staged probe grids and whose
  stability verdicts were measured under them. Pipeline phases now always
  stage the next step themselves, and `run()` refuses to fall through while
  a pipeline mode is active.
- **Offset-0 calibration was measured under the leftover probe grid**: when
  attribution completed, `_calibrate_step` re-ran the offset-0 battery while
  the last +30 probe grid was still live, recording it as natural data and
  poisoning the F-V curve anchor. The attribution baseline now counts as the
  offset-0 level (marked done) and completed levels are never re-measured.
- **A crashed attribution probe was consumed with zero data**: crash
  recovery left `calib_regime_index` past the end and phase 2 had no reset,
  so the re-run battery returned no windows and the probe row was credited
  as done without any measurement. It now resets the index and re-runs the
  full probe battery, like the calibration sweep does.
- **"refine current grid" was a silent no-op after a completed run**:
  `should_continue()` saw `status == "completed"` and returned before the
  loop; the GUI reported "Optimization finished!" with the old numbers.
  Seeding refinement (and re-selecting classic search on a completed run)
  now re-opens the state so Start actually runs.
- **Start on a cancelled reboot measured stale hardware**: a staged
  CurveShaper grid only goes live at the next POST; `run()` assumed any
  `waiting_reboot` state meant "we just rebooted". It now compares the
  uptime recorded at staging against the current uptime and raises a clear
  `RebootRequired` error (status preserved) instead of recording old
  hardware data under the new offset.
- **PROCTHROTTLEMAX residue after a hard crash**: the cap persists in the
  power plan, so a crash mid mid/low window left it behind and every later
  window (including idle/peak of re-run levels) was measured throttled.
  Each battery session now re-asserts 100% defensively.
- **Missing stress verdicts passed the stability gate**: a y-cruncher run
  killed without a usable verdict (`None`) counted as stable for the
  all-core/mid/low windows; the gate now fails closed.
- **WHEA event-log query failures were silently treated as "0 errors"**:
  `check_whea_errors` now raises `MeasurementError` when the query itself
  fails, so an unstable configuration can no longer pass because the log
  was unreadable.
- Derivation: temperature predictions are recomputed after a frequency-cap
  pullback and after a mid/low ineffective-regime fallback (previously the
  report showed predictions for an offset the solver did not choose);
  `_inverse_interp` docstring now matches its deepest-first scan order.
- GUI: **Reset State** now removes the logon autostart task (it previously
  lingered and relaunched the GUI for a run that no longer exists).
- `POST_BOOT_DELAY` is now actually used as the post-boot settle time
  (previously hardcoded to 5 s while the config documented 30 s).
- Documentation: reboot-count estimates unified (calibrate ≈ 8–10,
  attribute + calibrate ≈ 13–15).

### Changed
- **License switched from MIT to GPL-3.0-or-later**: full GPLv3 text in
  `LICENSE`; `SPDX-License-Identifier` headers added to all Python sources.
- **Documentation restructured into a bilingual `docs/` tree** (English +
  中文): full manual, quick start, calibration-pipeline deep-dive and
  contributing guide per language under `docs/en/` and `docs/zh/`;
  the root `README.md` is now a bilingual landing page linking into
  `docs/`. Superseded root documents removed
  (`QUICKSTART.md`, `CONTRIBUTING.md`, and the stale v1.0-era snapshots
  `PROJECT_COMPLETE.md` / `PROJECT_SUMMARY.md` — their content lives on,
  updated, in `docs/`).
- Documentation no longer names the external SMU probe toolchain; it is
  referenced only via this project's probe config keys.
  Stale `GITHUB_SETUP.md` snapshot removed as well.
- **No personal paths in the repository**: the SMU probe toolchain location
  is now resolved from the `PROBE_TOOLS_DIR` environment variable
  (recommended, `setx PROBE_TOOLS_DIR "<dir>"`) or a project-local
  `probe-tools/` folder; the previously hardcoded absolute paths are gone
  from `config.py`, `verify-setup.cmd`, `verify-setup.ps1` and
  `scripts/verify-temp.ps1` (which also accepts `-ProbeDir`). A missing
  toolchain now raises a clear setup error instead of a bare path-not-found.
- **Probe toolchain renamed to `acsprobe`** (Auto Curve Shaper probe):
  expected layout `<toolchain>\acsprobe\acsprobe.exe`; config keys
  `CS_PROBE_DIR`/`CSPROBE_EXE` renamed to `PROBE_TOOLS_DIR`/`PROBE_EXE`
  (`run_csprobe()` → `run_probe()`). Its wire format (AOD WMI object,
  value encoding, Tctl SMN read) is documented in
  `docs/en/PROBE.md` / `docs/zh/PROBE.md`.

## [1.5.0] - 2026-09-04

### Added
- **Model-first calibration pipeline** (`calibrate` mode, the new default in
  the GUI): instead of blind per-cell binary search, the tool first builds
  three calibration tables — frequency-voltage, frequency-temperature,
  voltage-temperature — then derives the optimal 5×3 grid from them.
  - **Full-spectrum battery** (`calibration.py`): one reboot per uniform
    offset level (7 levels), each session measuring five frequency bands:
    idle (no load), peak (affinity-pinned single-core burn workers),
    all-core (y-cruncher VT3, its verdict doubles as the stability gate),
    mid/low (all-core load under `PROCTHROTTLEMAX` 99/75% via `powercfg`).
    Every window records `(offset, regime, freq, temp, stable, whea)` — one
    row feeds all three tables. Total pipeline cost: ~8-14 reboots versus
    100-200 for the classic search.
  - **Temperature telemetry** (`temperature_monitor.py`): Tctl sampled at
    ~2 Hz via an SMN `0x59800` read (ZenStates-Core/WinRing0). Requires
    elevation; persistent failure aborts a calibration run (temperature is
    load-bearing data there) but only warns in classic mode.
  - **Differential attribution experiment** (optional, `attribute + calibrate`
    mode): one CS row at +30 per reboot against the offset-0 baseline builds
    the regime→row map empirically instead of trusting the built-in default.
  - **Derivation solver** (`derive.py`, pure logic, offline-testable): per
    regime takes the deepest stable offset (stability boundary), backs off a
    safety margin, clamps against user limits — **Max Temp (°C), Max Freq
    (MHz), Max Offset (+V cap)**, all settable in the GUI — and emits the
    derived grid plus a per-regime report. Ineffective throttled regimes
    (frequency never landed below the all-core window) fall back to the
    all-core boundary. A frequency cap is walked back along the regime's own
    F-V curve; an unreachable temperature cap is reported as a warning.
  - **Real final validation**: the converged/derived grid is now actually
    rebooted in and stress-tested before the run reports "completed" (1.4
    only staged the final grid). Tracked via `current_phase =
    "final_validation"` so reboot machinery cannot clobber it.
- **Crash-resume for calibration**: a session that dies mid-battery keeps
  status `battery_running`; on the next boot the windows that never ran are
  credited as UNSTABLE for the staged offset and the sweep continues.
- **Refine current grid** GUI mode: re-runs the per-cell search over the
  live grid (the residual engine), for use after a derived grid.
- `scripts/verify-temp.ps1`: elevated Tctl sampling self-test.
- `tests/test_derive.py` and `tests/test_pipeline.py`: offline tests for the
  solver and the full calibrate→derive→verify state machine (mocked hardware,
  ~8 simulated reboots).

## [1.4.0] - 2026-09-03

### Added
- **Auto-reboot (fully unattended runs)**: after each test iteration the GUI
  shows a cancelable 60s countdown ("Cancel Reboot" button), then reboots via
  `shutdown /r`. Combined with the logon auto-continue task, the entire
  100-200-reboot optimization loop proceeds unattended. `AUTO_REBOOT = False`
  restores manual reboots; `AUTO_REBOOT_DELAY` configures the countdown.
  Stop / Exit / Reset all cancel a pending countdown; exiting during the
  final 5s shutdown window aborts the OS shutdown.

### Fixed
- Single-instance lock rewritten as a kernel byte-range lock
  (msvcrt.locking). The previous PID-in-file + liveness-check scheme gave
  false positives after a reboot (Windows reuses PIDs, so the relaunched GUI
  saw the old PID as "alive" and exited with "Already Running" — stalling
  the unattended loop at exactly that point). Kernel locks are released by
  the OS when the holder dies, so crashes, hard kills and reboots can never
  produce a stale or false-positive lock.
- A second instance blocked by the lock no longer unregisters the autostart
  task on exit (it would have dismantled the running instance's auto-resume).
- The post-logon auto-continue no longer pops the "Continue Optimization?"
  confirmation — that dialog blocked the unattended loop at every reboot.
  Auto-resume starts silently; confirmations remain for manual clicks only.
- Load-frequency sampling crashed with TypeError on first use
  (`_spawn_ycruncher() missing log_path`) — the y-cruncher log-file redirect
  was applied to the stability path but not the load path. Verified
  end-to-end on real hardware (load sampling + stability verdict).
- A "failed" run is now resumable: pressing Start retries from the saved
  position instead of exiting immediately, so transient failures (power
  loss, workload hiccups, fixed bugs) don't require manual state surgery.
- Countdown text (auto-continue / auto-reboot) was being overwritten by the
  periodic display refresh; both now render through `_update_display` with
  countdown priority.

## [1.3.0] - 2026-09-03

### Added
- **y-cruncher stress testing**: stability tests and load-frequency sampling
  now run y-cruncher (VT3) when installed at `y-cruncher\y-cruncher.exe` —
  it detects computation errors, which burn.exe (crash-only, still supported
  as fallback) cannot. Verdict lines ("Running VT3: Passed/Error") are parsed
  from a log file (piped stdout breaks y-cruncher's time limit); an early
  exit without completing the window raises MeasurementError instead of
  silently passing with no load.
- **Logon auto-continue (Task Scheduler)**: starting an optimization
  registers a highest-privileges logon task that relaunches the GUI with
  `--continue`; after each manual reboot the GUI opens by itself and resumes
  after a 10s abortable countdown. The task is removed when the run
  completes, is stopped, fails, or the state is reset.
- Single-instance lock (`gui.lock`) with dead-PID takeover, so a crashed
  session can't block startup and a logon relaunch can't double-run.

### Fixed
- `run_command` now decodes subprocess output with `errors='replace'`:
  localized (GBK) output from schtasks/PowerShell crashed the reader thread
  on Chinese Windows.
- Autostart task registration moved from schtasks to the PowerShell
  ScheduledTasks API (schtasks mangles arguments embedded in /TR).

## [1.2.0] - 2026-09-03

### Added
- **Multi-sweep refinement**: CurveShaper cells interact (shaper influence
  fields overlap, per SkatterBencher's measurements), so after the first full
  pass every cell is re-searched, seeded from its previous optimum, until a
  full sweep changes nothing (converged) or `MAX_SWEEPS` is reached (default
  3; set to 1 for v1.1 behavior). A ±2-step convergence deadband keeps
  binary-search jitter from triggering endless sweeps. `MAX_REBOOT_ATTEMPTS`
  raised 100 → 350 accordingly. The GUI shows a new "Sweep" progress row.
- Temperature anchor labels corrected to -5°C / 50°C / 90°C (previously
  0/50/100°C; display-only — the interface takes column indices).
- State-machine simulation test (`logs/test_sweeps.py`): runs the full
  reboot cycle in-memory with faked hardware, covering flat/interaction/
  migration scenarios.

### Fixed
- Final validation now applies the **converged grid** (every cell's final
  optimum) instead of `best_grid` (a best-frequency snapshot that could
  predate later refinements).
- Resumed sessions no longer re-seed an exhausted sweep queue (prevented
  sweep boundaries from ever being reached across reboots).
- `state.json` writes are now atomic (temp file + `os.replace` + fsync):
  saving right before a reboot could previously be killed mid-write and
  corrupt weeks of progress.
- `test_results` in state.json is capped at the 20 most recent entries
  (full history stays in the logs); unbounded growth made every save slower
  across hundreds of reboots.
- Seeded refinement searches start their search range at the seed instead of
  re-scanning from 0.

### Changed
- Optimization report now includes `sweeps_completed` and `converged`.

## [1.1.0] - 2026-09-03

### Changed
- **GUI-only release**: removed the CLI entry point (`main.py`, `run.cmd`).
  The GUI (`run-gui.cmd` / `run-gui.ps1`) is now the only interface.
- Documentation updated accordingly (README, QUICKSTART, CONTRIBUTING,
  verify-setup scripts).

### Added
- Python 3.12 verified in the dev environment; all modules compile and
  import cleanly, with smoke tests for the clocks CSV parser and state
  round-trip (unknown-field tolerance).

## [1.0.1] - 2026-09-03

### Fixed
- **Frequency measurement pipeline**: now reads the CSV file produced by
  clocks-sample.ps1 and converts % Processor Performance to MHz via the base
  clock. The old stdout regex could never match, so every offset was judged
  unstable and the optimizer found nothing. Measurement failures now raise
  MeasurementError and fail the run instead of being mislabeled as instability.
- **Binary search**: `best_stable_offset` is reset when starting each cell;
  previously a later cell inherited the previous cell's optimum and could
  record an unsafe offset.
- **Hardware/state divergence**: the converged optimum is written back to the
  hardware cell after each cell completes; previously the last (often
  unstable) test value lingered during subsequent cells' tests.
- **cs_set_grid**: writes all cells including zeros so stale test values are
  always overwritten; previously zero cells were skipped and the final applied
  grid could differ from the reported best grid.
- **WHEA detection**: polls are incremental (persisted `last_whea_check`
  timestamp) and run again after the stress test, so errors are attributed to
  the correct configuration instead of a fixed 10-minute window.
- **Load sampling timeout**: added startup margin (previously timed out
  intermittently because burn ramp-up + PowerShell startup exceeded the
  timeout).
- **GUI**: worker threads no longer touch tkinter directly (UI task queue);
  display follows the optimizer's live state across reboot cycles; Stop/Exit
  terminate burn.exe so no orphaned workload keeps the CPU pinned.
- **state.json resilience**: unknown fields are ignored on load, and an
  unloadable state file is backed up instead of being silently replaced.
- **verify-setup.ps1**: Python detection no longer reports "[OK] Python
  found" when python is missing (native command failures don't throw in
  PowerShell).
- Probe invocations now have a 60s timeout instead of hanging forever.

## [1.0.0] - 2026-09-03

### Added
- Initial release of Auto Curve Shaper
- Core optimization engine with binary search algorithm
- Reboot-persistent state management
- Frequency monitoring (idle and load)
- Stability testing with WHEA error detection
- Modern GUI with real-time progress display
- 5×3 CurveShaper grid visualization
- CLI mode for command-line usage
- Comprehensive documentation (README, QUICKSTART, CONTRIBUTING)
- Launch scripts for both GUI and CLI modes
- Administrator privilege checking
- Automatic state recovery after reboot
- Configurable optimization parameters
- Result logging and reporting

### Features
- **Optimization Target**: Maximum CPU frequency
- **Algorithm**: Binary search per cell with stability validation
- **Grid Size**: 5 rows × 3 columns (15 cells total)
- **Offset Range**: -30 to +30 (starts conservatively at -5)
- **Optimization Order**: Min → Max → High → Low → Mid rows
- **Safety**: WHEA error detection, automatic rollback, conservative limits
- **GUI**: Real-time grid display, progress tracking, log output
- **CLI**: Detailed console output, status reporting
- **Persistence**: JSON state file survives crashes and power loss

### Technical Details
- Python 3.8+ (standard library only, no external dependencies)
- Tkinter GUI (included with Python)
- Windows-only (ACPI AOD WMI interface)
- AMD Zen 5 (Ryzen 9000) support
- Integration with external SMU probe tools
- Automatic reboot cycle management

### Documentation
- README.md: Complete project documentation
- QUICKSTART.md: 5-minute setup guide
- CONTRIBUTING.md: Contribution guidelines
- GITHUB_SETUP.md: Git and GitHub setup instructions
- PROJECT_SUMMARY.md: Project completion summary
- LICENSE: MIT License

### Known Limitations
- Requires manual reboot between iterations
- Windows-only (probe toolchain limitation)
- Single-threaded optimization
- Requires external SMU probe tools (not bundled)
- AMD Zen 5 only (not tested on other architectures)

### System Requirements
- AMD Ryzen 9000 (Zen 5) CPU
- Windows 10/11
- Python 3.8 or higher
- Administrator privileges
- External SMU probe tools

---

## [Unreleased]

### Planned Features
- Automatic reboot support (startup task)
- Unit test suite
- CI/CD pipeline
- Faster testing mode
- Multi-CPU model support validation
- Result visualization charts
- Configuration import/export
- Remote monitoring capability

### Potential Enhancements
- Additional optimization targets (power, efficiency)
- Machine learning prediction
- Web UI option
- Linux support (if feasible)
- Multi-threaded parallel testing

---

## Version History

- **v1.0.0** (2026-09-03): Initial release with full feature set
- **v0.9.0** (2026-09-03): Beta testing version (internal)
- **v0.5.0** (2026-09-03): Core engine completion
- **v0.1.0** (2026-09-03): Project initialization

---

## Migration Guide

### From Manual Probe Testing

If you were manually testing CurveShaper values with the probe tool:

1. **Backup your current settings**:
   ```bash
   # Record your current HYDRA or manual settings
   ```

2. **Clear existing settings**:
   ```bash
   cs-clear -f
   ```

3. **Run Auto Curve Shaper**:
   ```bash
   python gui.py  # or python main.py
   ```

4. **Compare results**:
   - Manual settings: Check your recorded values
   - Auto settings: Check `results/` directory
   - Validate in HYDRA or with longer stability tests

### State File Format

The `state.json` file structure:
```json
{
  "iteration": 15,
  "total_reboots": 45,
  "current_grid": [[...], ...],
  "best_grid": [[...], ...],
  "best_frequency": 5247.0,
  "cells_optimized": [...],
  "current_cell": [row, col],
  "search_min": -30,
  "search_max": 0,
  "search_current": -15,
  "best_stable_offset": -20,
  "status": "running",
  "current_phase": "optimize_min"
}
```

---

## Credits

### Built On
- **ZenStates-Core**: SMU interface library by irusanov
- **burn.exe**: CPU stress testing utility

### Inspired By
- HYDRA: Visual CurveShaper interface
- CoreCycler: CPU stability testing methodology
- AMD Ryzen Master: Official overclocking tool

### Special Thanks
- AMD for Zen 5 architecture
- Community testers and early adopters
- Open-source contributors

---

## License

MIT License - See LICENSE file for details

Copyright (c) 2026 Auto Curve Shaper Contributors
