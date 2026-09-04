# SPDX-License-Identifier: GPL-3.0-or-later
"""
Phase 1 derivation: calibration tables -> derived 5x3 grid

The solver is pure logic (no hardware access) so it can be tested offline.
For every regime the calibration sweep produced (offset, freq, temp, stable)
points; the stable ones trace the F-V curve of that frequency band, and the
stability boundary is the deepest offset that survived stress.

Per CS row:
    chosen = deepest_stable + MARGIN           # back off from the boundary
    chosen = min(chosen, MAX_VOLTAGE_OFFSET)   # voltage cap
    chosen = clamp(chosen, MIN_SAFE_OFFSET)
    if freq_pred(chosen) > MAX_FREQ_LIMIT:     # frequency cap: walk the F-V
        chosen = offset_where_freq == cap      # curve back toward zero
    temp_pred(chosen) > MAX_TEMP_LIMIT  ->  warning (not fixable by CS alone:
    deeper undervolt cools but is unstable at that point)

Ineffective throttled regimes (frequency statistically equal to the all-core
window — PROCTHROTTLEMAX had no effect on this system) fall back to the
all-core boundary instead of trusting a boundary they never exercised.
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config import (
    ATTRIBUTION_MAP, CALIB_MARGIN, CS_COLS, CS_ROWS, MAX_FREQ_LIMIT,
    MAX_TEMP_LIMIT, MAX_VOLTAGE_OFFSET, MIN_SAFE_OFFSET,
    REGIME_EFFECTIVE_DELTA_MHZ, ROW_NAMES,
)

logger = logging.getLogger(__name__)


@dataclass
class RegimeDerivation:
    regime: str
    row: int
    deepest_stable: Optional[int] = None
    first_unstable: Optional[int] = None
    unbounded: bool = True          # no unstable point seen in the sweep
    effective: bool = True          # throttled regimes only
    chosen_offset: int = 0
    freq_pred: float = 0.0
    temp_pred: float = 0.0
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            'regime': self.regime,
            'row': self.row,
            'row_name': ROW_NAMES[self.row] if 0 <= self.row < CS_ROWS else str(self.row),
            'deepest_stable': self.deepest_stable,
            'first_unstable': self.first_unstable,
            'unbounded': self.unbounded,
            'effective': self.effective,
            'chosen_offset': self.chosen_offset,
            'freq_pred_mhz': round(self.freq_pred),
            'temp_pred_c': round(self.temp_pred, 1),
            'notes': self.notes,
        }


@dataclass
class DeriveReport:
    grid: List[List[int]]
    regimes: List[RegimeDerivation]
    warnings: List[str]
    peak_freq_pred: float = 0.0

    def as_dict(self) -> dict:
        return {
            'grid': self.grid,
            'regimes': [r.as_dict() for r in self.regimes],
            'warnings': self.warnings,
            'peak_freq_pred_mhz': round(self.peak_freq_pred),
        }


# A battery row: {offset, regime, freq_max, temp_max, stable, ...}
# Rows tagged with probe=... come from the attribution experiment (one CS row
# deliberately at +30) and never describe the natural curve — excluded.
def _split_by_regime(calib_rows: List[dict]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for r in calib_rows:
        if r.get('probe') is not None:
            continue
        out.setdefault(r['regime'], []).append(r)
    for pts in out.values():
        pts.sort(key=lambda r: r['offset'])
    return out


def _boundary(pts: List[dict]) -> Tuple[Optional[int], Optional[int]]:
    """(deepest_stable, first_unstable) offset pair; None = never seen

    Unstable points SHALLOWER than a stable point contradict monotonicity
    (deeper offset = less stable). They are crash residue — e.g. a session
    that died mid-battery was credited unstable, then the level was re-run
    and measured stable — and are dropped instead of poisoning the boundary.
    """
    stable = [r['offset'] for r in pts if r.get('stable') and (r.get('freq_max') or 0) > 0]
    unstable = [r['offset'] for r in pts if not r.get('stable')]
    if stable and unstable:
        unstable = [u for u in unstable if u < min(stable)]
    return (min(stable) if stable else None,
            max(unstable) if unstable else None)


def _freq_curve(pts: List[dict]) -> List[Tuple[int, float]]:
    """Stable (offset, freq) points ascending by offset"""
    return [(r['offset'], r['freq_max']) for r in pts
            if r.get('stable') and (r.get('freq_max') or 0) > 0]


def _temp_curve(pts: List[dict]) -> List[Tuple[int, float]]:
    """(offset, temp_max) points ascending by offset (all rows)"""
    return [(r['offset'], r.get('temp_max') or 0.0) for r in pts]


def _interp(points: List[Tuple[int, float]], x: int) -> float:
    """Piecewise-linear interpolation, flat at the ends"""
    if not points:
        return 0.0
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _inverse_interp(points: List[Tuple[int, float]], target: float) -> Optional[int]:
    """Offset whose interpolated freq == target, truncated toward zero.

    Expects freq decreasing with increasing offset (undervolt raises clocks);
    segments are scanned deepest-first, so on the expected monotonic curve
    the single crossing is found. Truncation toward zero lands on the
    shallower (lower-frequency) side, so a freq CAP is never exceeded by
    linear-interpolation error.
    Returns None if target lies outside the data range.
    """
    if not points:
        return None
    # points ascending by offset => freq descending
    hi_freq = points[0][1]   # deepest offset
    lo_freq = points[-1][1]  # shallowest offset
    if not (lo_freq <= target <= hi_freq):
        return None
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        f0, f1 = max(y0, y1), min(y0, y1)
        if f0 >= target >= f1:
            if y1 == y0:
                return x0
            frac = (y0 - target) / (y0 - y1)
            # Truncate toward zero: a freq CAP must land at-or-below target,
            # and the shallower offset is the lower-frequency side
            return int(x0 + (x1 - x0) * frac)
    return None


def derive_grid(
    calib_rows: List[dict],
    attribution: Dict[str, int] = None,
    margin: int = CALIB_MARGIN,
    max_temp: float = MAX_TEMP_LIMIT,
    max_freq: float = MAX_FREQ_LIMIT,
    max_voltage: int = MAX_VOLTAGE_OFFSET,
) -> DeriveReport:
    attribution = dict(attribution or ATTRIBUTION_MAP)
    by_regime = _split_by_regime(calib_rows)
    warnings: List[str] = []
    derivations: List[RegimeDerivation] = []
    chosen_by_regime: Dict[str, int] = {}

    # First pass: raw boundary + caps per regime (regime-internal logic)
    for regime in attribution:
        pts = by_regime.get(regime, [])
        d = RegimeDerivation(regime=regime, row=attribution[regime])

        if not pts:
            d.chosen_offset = max_voltage
            d.notes.append("no calibration data — offset left at voltage cap")
            warnings.append(f"regime {regime}: no data in calibration tables")
            derivations.append(d)
            chosen_by_regime[regime] = d.chosen_offset
            continue

        d.deepest_stable, d.first_unstable = _boundary(pts)
        d.unbounded = d.first_unstable is None
        curve = _freq_curve(pts)

        if d.deepest_stable is None:
            d.chosen_offset = max_voltage
            d.notes.append("never stable in the sweep — offset pinned at voltage cap")
            warnings.append(f"regime {regime}: no stable point; offset pinned at {max_voltage:+d}")
            d.freq_pred = _interp(curve, d.chosen_offset)
            d.temp_pred = _interp(_temp_curve(pts), d.chosen_offset)
            derivations.append(d)
            chosen_by_regime[regime] = d.chosen_offset
            continue

        if d.unbounded:
            d.notes.append("sweep never broke stability — boundary is the deepest swept level")

        chosen = d.deepest_stable + margin
        chosen = max(chosen, d.deepest_stable)      # never more aggressive than proven stable (negative-margin guard)
        chosen = min(chosen, max_voltage)           # voltage cap: upper clamp toward positive
        chosen = max(chosen, MIN_SAFE_OFFSET)

        d.chosen_offset = chosen
        d.freq_pred = _interp(curve, chosen)
        d.temp_pred = _interp(_temp_curve(pts), chosen)
        derivations.append(d)
        chosen_by_regime[regime] = chosen

    # Frequency cap: walk each affected regime back along its own F-V curve
    if max_freq and max_freq > 0:
        for d in derivations:
            if d.freq_pred <= max_freq:
                continue
            curve = _freq_curve(by_regime.get(d.regime, []))
            off = _inverse_interp(curve, max_freq)
            if off is None:
                d.notes.append(
                    f"freq cap {max_freq:.0f} MHz below every stable point — "
                    "staying at the stability-derived offset")
                warnings.append(
                    f"regime {d.regime}: cannot reach {max_freq:.0f} MHz cap "
                    "inside the stable range")
            else:
                off = max(off, d.deepest_stable or MIN_SAFE_OFFSET)
                d.notes.append(f"freq cap: {d.chosen_offset:+d} -> {off:+d}")
                d.chosen_offset = off
                d.freq_pred = _interp(curve, off)
                d.temp_pred = _interp(_temp_curve(by_regime.get(d.regime, [])), off)
            chosen_by_regime[d.regime] = d.chosen_offset

    # Temperature cap: undervolt cools, so a violation at the stability
    # boundary means the cap is unreachable via CS offsets alone
    for d in derivations:
        if max_temp and d.temp_pred > max_temp:
            d.notes.append(
                f"temp {d.temp_pred:.0f} °C > cap {max_temp:.0f} °C at the "
                "stability boundary — needs better cooling, not more offset")
            warnings.append(f"regime {d.regime}: temperature cap unreachable")

    # Throttled-regime effectiveness: a mid/low window that did not actually
    # land below the all-core window never exercised its band
    allcore_freq = next((d.freq_pred for d in derivations if d.regime == "allcore"), 0.0)
    allcore_chosen = chosen_by_regime.get("allcore")
    for regime in ("mid", "low"):
        d = next((x for x in derivations if x.regime == regime), None)
        if d is None or allcore_chosen is None:
            continue
        curve = _freq_curve(by_regime.get(regime, []))
        if curve and allcore_freq and (max(f for _, f in curve) >= allcore_freq - REGIME_EFFECTIVE_DELTA_MHZ):
            d.effective = False
            d.notes.append(
                f"window did not land below all-core ({max(f for _, f in curve):.0f} vs "
                f"{allcore_freq:.0f} MHz) — falling back to the all-core boundary")
            d.chosen_offset = allcore_chosen
            # keep the report honest: predictions now describe the offset the
            # solver actually chose, interpolated on this regime's own curves
            d.freq_pred = _interp(curve, allcore_chosen)
            d.temp_pred = _interp(_temp_curve(by_regime.get(regime, [])), allcore_chosen)

    grid = [[0] * CS_COLS for _ in range(CS_ROWS)]
    peak_pred = 0.0
    for d in derivations:
        if 0 <= d.row < CS_ROWS:
            # v1: one offset per row across all three temperature columns —
            # the sweep cannot separate them yet; the residual-refinement
            # engine is free to split columns afterwards
            for c in range(CS_COLS):
                grid[d.row][c] = d.chosen_offset
        peak_pred = max(peak_pred, d.freq_pred)

    return DeriveReport(grid=grid, regimes=derivations,
                        warnings=warnings, peak_freq_pred=peak_pred)
