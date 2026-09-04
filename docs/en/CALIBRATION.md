# The Calibration Pipeline — Design Deep-Dive

Why v1.5 builds three tables before touching CurveShaper, how the load
battery lands on each frequency band, and how the solver picks the optimal
grid. For day-to-day usage see [QUICKSTART.md](QUICKSTART.md); for the full
manual see [README.md](README.md).

其他语言 / Other language: [中文版](../zh/CALIBRATION.md)

---

## 1. The idea: model first, apply second

CurveShaper's 5×3 grid is the product of three physical relationships:

| Table | CS grid meaning |
|---|---|
| **Frequency–Voltage** — stable frequency vs voltage offset per band | the 5 rows (Min/Low/Mid/High/Max) at a fixed temperature |
| **Frequency–Temperature** — frequency a band reaches vs Tctl | the same row across the 3 temperature columns |
| **Voltage–Temperature** — stability boundary drift vs temperature | boundary per (row, column) pair |

All three are 2-D slices of one 3-D surface: the maximum stable frequency
F(V, T). The classic search probes this surface blindly, one cell at a time
(3–7 reboots per cell × 15 cells × refinement sweeps). The pipeline probes
it *systematically* — 7 uniform-offset reboots fill all three tables at
once — and then solves for the grid.

Two properties make this work:

1. **Within the stable range, frequency rises monotonically as the voltage
   offset drops** (verified experimentally on hardware). The optimum is
   therefore *at* the stability boundary, not at an interior extremum —
   finding it is a boundary-detection problem, not a search problem.
2. **CS itself interpolates linearly between its anchor points.** The
   calibration data does not need to land exactly on the anchors; it needs
   to spread along the frequency axis, and the fit covers the rest.

## 2. Confirming the frequency points: attribution, not specification

The CS row is chosen by the CPU — the core's *measured* frequency decides
which row's offset carries weight. We cannot "set" a row; we can only land
on it. Two mechanisms handle this:

**Differential attribution experiment** (one-off, ~5 reboots). Probe one CS
row at +30 per reboot against the offset-0 battery; regimes whose frequency
moves (≥100 MHz, either direction — sensitivity is the signal, not
direction) belong to that row. One-off +30 staging tests already demonstrated half
the map: Min +30 moved idle clocks, High/Max +30 moved hot all-core clocks.

**Attribution by measured frequency, never by workload name.** Undervolt
shifts frequencies up; a window that started in the Mid band may drift into
High territory. Battery rows always carry the measured frequency, and the
solver attributes by regime map + measurement, treating the workload name
as a prior only. This residual mismatch is exactly the "cells interact"
phenomenon — the refinement engine exists to eat it.

## 3. The load battery: placing windows on the frequency axis

All load controls are runtime-effective, so reboots are spent *only* on CS
offset changes; the frequency-axis scan is free within each boot:

| Regime | Mechanism | Where it lands (9900X3D reference) |
|---|---|---|
| `idle` | no load | < 3 GHz sink + cold idle boost — Min row |
| `peak` | Python busy workers pinned to one logical core | ~5.3+ GHz single-core boost — Max row |
| `allcore` | y-cruncher VT3 (burn fallback), all threads | ~4.9–5.1 GHz hot sustained — High row |
| `mid` | all-core load + `powercfg` PROCTHROTTLEMAX = 99 % | ~4.4 GHz (boost off, base clock) — Mid row |
| `low` | all-core load + PROCTHROTTLEMAX = 75 % | ~3.3 GHz — Low row |

PROCTHROTTLEMAX is pure Windows power management: immediate effect, no
driver. If a power plan ignores it, the mid/low windows will show full
boost clocks — the solver detects this (the window's frequency never
dropped ≥150 MHz below the all-core window), flags the regime
"not effective", and conservatively reuses the all-core boundary.

Every window records `(offset, regime, freq, temp, stable, whea)`.
Temperature is sampled at ~2 Hz from Tctl (SMN `0x59800`, read via
the probe helper) on a background thread, giving the F-T and V-T tables their
temperature axis for free. The all-core window doubles as the level's
stability gate (y-cruncher verdict + WHEA deltas per window).

One session ≈ 10 minutes; one reboot per offset level × 7 levels ≈ 70–80
minutes for the whole calibration.

## 4. The solver: boundary + margin + caps

Per regime (mapped to its CS row):

```
boundary     = deepest stable offset seen in the sweep
chosen       = boundary + MARGIN                  # back off toward zero
chosen       = max(chosen, boundary)              # never more aggressive than proven
chosen       = min(chosen, MAX_VOLTAGE_OFFSET)    # voltage cap
chosen       = max(chosen, MIN_SAFE_OFFSET)
if freq_pred(chosen) > MAX_FREQ:                  # walk the F-V curve back
    chosen = offset_where(freq == MAX_FREQ)       # truncated toward zero
if temp_pred(chosen) > MAX_TEMP:                  # warning: undervolt cools, but
    ...                                           # deeper offsets are unstable
```

Details worth knowing:

- **The only free parameter is MARGIN.** Calibration-time stability
  (minutes of y-cruncher) is weaker evidence than week-long uptime, so the
  grid deliberately sits `MARGIN` offset-units (default 10 = 2 sweep steps)
  inside the boundary. If verification fails, raise the margin and
  re-derive — the tables don't change, so this costs one reboot, not a new
  calibration.
- **Frequency caps are enforced by inversion**: the solver finds the offset
  whose interpolated frequency equals the cap, truncating toward zero so
  linear-interpolation error can never overshoot the cap.
- **An unreachable temperature cap is reported, not fixed.** Undervolting
  cools, but at the stability boundary deeper offsets are impossible — the
  warning means "needs better cooling", not "retry with different offsets".
- **Degenerate data is handled conservatively**: never-stable → pinned at
  the voltage cap; unbounded sweep → flagged; contradictory crash residue
  (unstable rows shallower than stable ones violate monotonicity) → dropped.
- Each row's offset is written to **all three temperature columns**. The
  uniform sweep cannot separate columns yet; that is the first thing the
  residual refinement pass can improve.

## 5. Verify, then refine if needed

The derived grid is rebooted in and measured for real (the v1.4 tool only
staged its final grid without testing it). Outcomes:

- **Stable, frequency ≈ prediction** → done.
- **Unstable** → raise MARGIN, re-derive (tables unchanged).
- **Frequency below prediction in one band** → a cross-term the 2-D tables
  missed; run *refine current grid* — the classic per-cell engine, seeded
  from the derived values, eating exactly the residuals.

## 6. Crash resilience

State persists after every window. If Windows dies mid-battery:

- the next boot detects status `battery_running`,
- every window that never ran is credited **UNSTABLE** for the staged
  offset (dying under the staged grid *is* a stability verdict),
- the level is re-run later to gather real measurements, and the solver's
  monotonicity filter discards contradictory crash residue.

## 7. Known limitations

- **Mid/Low anchors are approximations.** Row anchor frequencies are
  fused, not exposed; throttled windows land *near* the band, not on it.
  CS interpolates anchors, so the fitted tables cover the gap.
- **Columns are not separated** by the uniform sweep (one offset per row
  across all columns); per-column refinement is future work / the
  refinement engine's job.
- **Attribution assumes one dominant row per regime.** Overlapping shaper
  fields blur this; the refinement pass absorbs the error.
- **Temperature is observed, not controlled** — the two natural anchors
  (cold idle, hot load) cover CS's cold/hot columns; the middle column is
  interpolated.

See also: [QUICKSTART.md](QUICKSTART.md) · [README.md](README.md) ·
[Contributing](CONTRIBUTING.md)
