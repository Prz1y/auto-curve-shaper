# Auto Curve Shaper — Full Documentation

Automatic AMD Zen 5 CurveShaper voltage-curve optimization tool.

- **Target platform:** AMD Ryzen 9000 (Zen 5) desktop CPUs (9900X3D verified)
- **Optimization goal:** maximum CPU frequency
- **Requirements:** Windows 10/11, Administrator privileges, Python 3.8+
- **License:** GPL-3.0-or-later — see [LICENSE](../../LICENSE)

Other languages / 其他语言：[中文文档](../zh/README.md)

---

## Overview

This tool automatically explores the CurveShaper voltage-curve space to find
the settings that maximize CPU frequency, with state that persists across
reboots (every CurveShaper change requires a reboot to apply; the tool
resumes automatically afterwards, unattended).

Two optimization flows are available:

| | Calibrate → Derive → Verify (default) | Classic per-cell search |
|---|---|---|
| Strategy | Model the stability surface first, then solve | Blind binary search per cell |
| Reboots | ~8–20 | ~100–200 |
| Result | Derived grid + per-regime report | Empirically converged grid |
| Best for | Repeatable runs, explicit limits | Squeezing the last residual MHz |

The classic engine is kept and doubles as the **residual refinement** tool
("refine current grid" in the GUI).

## How CurveShaper works

CurveShaper is a 5×3 grid of voltage offsets written through the ACPI AOD
interface (BIOS applies them to the SMU at the next POST — nothing takes
effect at runtime, and values are write-only):

| Frequency point | col 0 (~0 °C) | col 1 (~50 °C) | col 2 (~100 °C) |
|---|---|---|---|
| Min | ±30 | ±30 | ±30 |
| Low | ±30 | ±30 | ±30 |
| Mid | ±30 | ±30 | ±30 |
| High | ±30 | ±30 | ±30 |
| Max | ±30 | ±30 | ±30 |

- **Rows** (Min/Low/Mid/High/Max) follow the core's *frequency/activity*
  band: Min shapes idle/low-current boost, Max shapes single-core peak
  boost, High/Max shape sustained all-core load.
- **Columns** are temperature anchor points (hardware takes indices only;
  the labels are approximate).
- Offsets range **−30…+30** (step 1). More negative = lower voltage target;
  within the stable range, lower voltage ⇒ higher boost clocks.

## The v1.5 pipeline

### Phase 0 — Calibrate (build the tables)

The grid is set to a *uniform* offset, one reboot per level
(0, −5, −10, −15, −20, −25, −30 by default). After each boot the tool runs
the **full-spectrum battery** — five load windows covering the frequency
axis, each recording `(offset, regime, freq, temp, stable, whea)`:

| Window | Load mechanism | Frequency band | Duration |
|---|---|---|---|
| `idle` | none (cores sink) | Min row (cold boost) | 30 s |
| `peak` | Python busy workers pinned to one logical core (`SetThreadAffinityMask`) | Max row (single-core boost) | 90 s |
| `allcore` | y-cruncher VT3 (burn.exe fallback) | High row (hot sustained) | 180 s |
| `mid` | all-core load + `PROCTHROTTLEMAX=99` (boost off) | Mid row (~base clock) | 90 s |
| `low` | all-core load + `PROCTHROTTLEMAX=75` | Low row | 90 s |

Because the loads are runtime-effective, **one reboot yields five data
points** across the axis — this is where the reboot savings come from. The
all-core window doubles as the stability gate for the whole level
(y-cruncher verdict + per-window WHEA deltas). A crash mid-battery is
survivable: the remaining windows are credited as UNSTABLE for that offset
and the sweep continues after the next boot.

These rows fill three tables simultaneously:

- **frequency–voltage** — max stable frequency per offset per band
- **frequency–temperature** — frequency vs Tctl within a band
- **voltage–temperature** — stability boundary drift with temperature

Optional **attribution experiment** (`attribute + calibrate` mode): before
the sweep, one CS row is set to +30 per reboot (all other cells 0) and the
battery is compared against the offset-0 baseline. Regimes whose frequency
moves ≥100 MHz are *attributed* to that row — the regime→row map is then
measured, not assumed.

### Phase 1 — Derive (solve the optimal grid)

Pure logic over the tables (`derive.py`), per regime:

```
chosen = deepest_stable_offset + MARGIN      # back off from the boundary
chosen = min(chosen, max_voltage_offset)     # Max Offset cap
chosen = max(chosen, MIN_SAFE_OFFSET)
if predicted_freq(chosen) > MAX_FREQ:        # walk back along the F-V curve
    chosen = offset_where_freq == MAX_FREQ   # (truncated toward the cap)
if predicted_temp(chosen) > MAX_TEMP:        # warning — not fixable by CS
```

Each row gets its regime's offset across all three temperature columns (the
uniform sweep cannot separate them yet; residual refinement may).
Degenerate cases are handled conservatively:

- regime never stable in the sweep → offset pinned at the Max Offset cap
- sweep never broke stability → boundary flagged "unbounded"
- throttled window never landed below the all-core window
  (throttle ineffective on this system) → falls back to the all-core boundary

### Phase 2 — Verify

The derived grid is written, rebooted in, and actually stress-tested
(WHEA + idle/load frequency + y-cruncher) before the run reports
`completed`. If you want to squeeze residuals afterwards, run
**refine current grid** — the per-cell binary search, seeded from the live
grid, converging immediately when nothing moves.

## Classic search (v1.1–v1.4 flow)

1. Baseline with all offsets at 0 (1 reboot).
2. Per cell (priority: Min, Max, High, Low, Mid rows): binary search the
   most aggressive stable offset, 3–7 reboots per cell.
3. Cells interact, so refinement sweeps re-search every cell seeded from its
   previous optimum until a full sweep changes nothing (±2 deadband) or
   `MAX_SWEEPS` (default 3) is reached.
4. Final validation: the converged grid is rebooted in and stress-tested.

Select "classic search" in the GUI; select "refine current grid" to re-run
the per-cell pass over whatever grid is live.

## Architecture

```
auto-curve-shaper/
├── gui.py                   # GUI application (entry point)
├── optimizer.py             # Orchestration: pipeline phases + classic search
├── calibration.py           # Full-spectrum battery + attribution experiment
├── derive.py                # Solver: boundaries + margin + caps -> 5x3 grid
├── workload.py              # Load battery (affinity workers, powercfg throttle)
├── temperature_monitor.py   # Tctl telemetry (SMN read)
├── state_manager.py         # Reboot persistence and state tracking
├── frequency_monitor.py     # CPU frequency measurement
├── utils.py                 # Utility functions and probe wrapper
├── config.py                # Configuration parameters
├── scripts/
│   └── verify-temp.ps1      # Elevated Tctl sampling self-test
├── tests/
│   ├── test_derive.py       # Solver tests (synthetic tables)
│   └── test_pipeline.py     # Full pipeline state machine (mocked hardware)
├── docs/                    # This documentation (en/ + zh/)
├── run-gui.cmd / run-gui.ps1
├── state.json               # Run state (auto-generated, gitignored)
├── results/                 # Test results (auto-generated, gitignored)
└── logs/                    # Execution logs (auto-generated, gitignored)
```

## Usage

### Prerequisites

1. AMD Ryzen 9000 (Zen 5) CPU on Windows 10/11
2. Python 3.8+ (tkinter included)
3. An external SMU probe toolchain for CurveShaper writes and SMN reads
   (not bundled with this repository) — set `CS_PROBE_DIR` in `config.py`
   to its location
4. y-cruncher (recommended): download the Windows x64 build from
   [numberworld.org](https://www.numberworld.org/y-cruncher/), unpack into
   the project's `y-cruncher\` folder. Without it the tool falls back to
   burn.exe, which detects crashes only — not computation errors.
5. Run `scripts\verify-temp.ps1` (elevated) once to confirm Tctl telemetry
   works on your board.

### Running

Right-click `run-gui.cmd` → **Run as Administrator** (or run
`run-gui.ps1` from an elevated PowerShell).

The **Pipeline & Limits** panel:

- **Mode** — `calibrate` (default pipeline), `attribute + calibrate`
  (adds 5 probe reboots), `classic search`, `refine current grid`
- **Max Temp (°C)** — temperature cap, default 90
- **Max Freq (MHz, 0=off)** — frequency cap; the solver walks the F-V curve
  back so no band exceeds it
- **Max Offset (+V cap)** — upper clamp on derived offsets; 0 forbids
  positive (over-voltage) offsets
- **Safety Margin** — offset units backed off from each stability boundary
  (default 10)

Click **Start**. From then on the run is unattended:

- after each reboot-needing step: 60 s cancelable countdown ("Cancel
  Reboot"), then `shutdown /r`
- at logon, a Task Scheduler task relaunches the GUI elevated with
  `--continue`; after a 10 s countdown the run resumes (closing the window
  aborts). The task is removed when the run ends.
- Set `AUTO_REBOOT = False` in `config.py` for manual reboots instead.

Intervening: **Stop** kills the stress workload (the run ends at the next
reboot prompt), **Reset State** wipes progress, **Exit** cancels a pending
countdown and shutdown.

### After each reboot

Nothing. The tool detects the post-reboot state, continues, and proceeds.
Interrupted runs (crash, power loss) resume from `state.json`; a run that
crashed *during a calibration battery* credits the windows that never ran
as unstable for that offset and moves on.

## Configuration highlights (`config.py`)

```python
CALIB_OFFSETS = [0, -5, -10, -15, -20, -25, -30]  # sweep levels (reboots)
CALIB_REGIMES = ["idle", "peak", "allcore", "mid", "low"]
CALIB_ALLCORE_DURATION = 180     # y-cruncher gate per level, seconds
MID_THROTTLE_PCT = 99            # 99% max processor state = boost off
LOW_THROTTLE_PCT = 75
CALIB_MARGIN = 10                # offset units from the boundary
MAX_TEMP_LIMIT = 90              # caps, overridable in the GUI
MAX_FREQ_LIMIT = 0               # 0 = no cap
MAX_VOLTAGE_OFFSET = 0           # no positive offsets
STABILITY_TEST_DURATION = 300    # classic mode stress window
MAX_SWEEPS = 3                   # classic mode refinement cap
MAX_REBOOT_ATTEMPTS = 350        # hard stop
AUTO_REBOOT = True               # False = manual reboots
```

## State & output

- `state.json` — full run state (atomic writes; survives crashes; a corrupt
  file is backed up automatically). Deleting it = fresh start.
- `results/` — JSON test results, final grids.
- `logs/` — timestamped logs, y-cruncher output, per-window frequency CSVs.
- The GUI shows live grid state, calibration progress
  (levels × windows), mode, caps, best frequency.

## Troubleshooting

| Symptom | Fix |
|---|---|
| WinRing0 driver init failure / "Administrator Required" | Run the GUI elevated (right-click `run-gui.cmd`) |
| Probe executable not found | Check `CS_PROBE_DIR` / `CSPROBE_EXE` in `config.py` |
| Frequencies not measured | Check `clocks-sample.ps1`; `Set-ExecutionPolicy RemoteSigned` |
| "no Tctl samples" | Run `scripts\verify-temp.ps1` elevated; some boards need a newer probe build |
| WHEA errors after a reboot | That level was too aggressive — the tool rolls back automatically; manual recovery: the probe's `cs-clear -f`, reboot |
| Boot loop after aggressive level | Clear CMOS; then use the probe toolchain's elevated runner to issue `cs-clear -f` |
| mid/low windows show full boost clocks | `PROCTHROTTLEMAX` has no effect on this power plan — the solver detects this (regime flagged "not effective") and falls back to the all-core boundary |

## Safety features

- Conservative starting points, stability gate on every calibration level
- WHEA Event-19 monitoring, attributed per test window
- Automatic rollback of unstable configurations
- Crash-safe state persistence (atomic writes, corrupt-file backup)
- Caps are enforced at derivation time; an unreachable temperature cap is
  reported, never silently ignored

## Risks & warnings

⚠️ **Use at your own risk.** Aggressive undervolting can cause instability,
WHEA errors, or boot failures requiring CMOS clearing. Silicon lottery
applies; not all CPUs tolerate the same offsets. Run on a test machine,
keep an eye on temperatures, and never leave the tool running unattended on
a production system's first calibration.

## Credits

Built on top of **ZenStates-Core** (irusanov, SMU interface),
**y-cruncher** (Xavier Gagnon, stability testing), and the SkatterBencher
Curve Shaper measurements.

## License

Copyright (C) 2026 Auto Curve Shaper Contributors.

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option)
any later version. See [LICENSE](../../LICENSE).

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
more details.
