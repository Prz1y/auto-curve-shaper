"""Offline smoke test for the derive.py solver (no hardware, synthetic tables).

Run:  python tests\\test_derive.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from derive import derive_grid


def row(offset, regime, freq, temp_max, stable):
    return {'offset': offset, 'regime': regime, 'freq_max': freq,
            'temp_max': temp_max, 'stable': stable}


def make_tables():
    """Realistic 9900X3D-ish sweep: allcore breaks at -25, idle never breaks,
    mid breaks at -20, low never lands below all-core (throttle ineffective)."""
    rows = []
    for off, f, t, s in [(0, 4985, 71, True), (-5, 5002, 74, True),
                         (-10, 5018, 77, True), (-15, 5029, 80, True),
                         (-20, 5037, 83, True), (-25, 0, 0, False),
                         (-30, 0, 0, False)]:
        rows.append(row(off, "allcore", f, t, s))
    for off, f, t in [(0, 4488, 42), (-5, 4520, 43), (-10, 4560, 44),
                      (-15, 4595, 46), (-20, 4630, 47), (-25, 4660, 48),
                      (-30, 4688, 50)]:
        rows.append(row(off, "idle", f, t, True))
    for off, f, t, s in [(0, 4400, 58, True), (-5, 4402, 59, True),
                         (-10, 4404, 60, True), (-15, 4405, 61, True),
                         (-20, 0, 0, False), (-25, 0, 0, False), (-30, 0, 0, False)]:
        rows.append(row(off, "mid", f, t, s))
    for off, f, t in [(0, 4980, 70), (-5, 4999, 73), (-10, 5015, 76),
                      (-15, 5026, 79), (-20, 5034, 82), (-25, 0, 0), (-30, 0, 0)]:
        rows.append(row(off, "low", f, t, True))  # low == allcore-like: ineffective
    for off, f, t, s in [(0, 5390, 55, True), (-5, 5415, 57, True),
                         (-10, 5432, 59, True), (-15, 5441, 62, True),
                         (-20, 5448, 64, True), (-25, 0, 0, False), (-30, 0, 0, False)]:
        rows.append(row(off, "peak", f, t, s))
    return rows


def main():
    tables = make_tables()
    report = derive_grid(
        tables,
        margin=10,
        max_temp=90,
        max_freq=0,
        max_voltage=0,
    )

    grid = report.grid
    by_row = {d.row: d for d in report.regimes}

    assert len(grid) == 5 and all(len(r) == 3 for r in grid), "grid shape"

    # allcore: deepest stable -20, margin 10 -> -10, pred ~5018, temp ~77 <= 90
    d = by_row[3]
    assert d.chosen_offset == -10, f"allcore chosen {d.chosen_offset}"
    assert 5010 <= d.freq_pred <= 5025, f"allcore freq_pred {d.freq_pred}"
    assert d.first_unstable == -25 and not d.unbounded

    # idle: unbounded (-30 deepest), margin -> -20, pred ~4630
    d = by_row[0]
    assert d.chosen_offset == -20, f"idle chosen {d.chosen_offset}"
    assert d.unbounded

    # mid: deepest stable -15 -> -5, pred ~4403
    d = by_row[2]
    assert d.chosen_offset == -5, f"mid chosen {d.chosen_offset}"
    assert d.effective

    # low: ineffective -> falls back to allcore's chosen (-10)
    d = by_row[1]
    assert not d.effective and d.chosen_offset == -10, \
        f"low fallback {d.chosen_offset} effective={d.effective}"

    # peak: deepest stable -20 -> -10, pred ~5432
    d = by_row[4]
    assert d.chosen_offset == -10, f"peak chosen {d.chosen_offset}"
    assert 5420 <= d.freq_pred <= 5445

    # grid rows carry their offset across all three columns
    for r in range(5):
        assert len(set(grid[r])) == 1, f"row {r} not uniform"

    # peak row drives the predicted peak
    assert abs(report.peak_freq_pred - by_row[4].freq_pred) < 1

    # --- freq cap: 5010 MHz caps the peak/Hot rows back along their curves ---
    report2 = derive_grid(tables, margin=10, max_temp=90, max_freq=5010, max_voltage=0)
    by_row2 = {d.row: d for d in report2.regimes}
    # peak pred at -10 is ~5432 > cap: inverse interp on peak curve for 5010
    # is below the deepest stable point's reach -> stays at stability offset + note
    d = by_row2[4]
    assert d.chosen_offset == -10 and any("freq cap" in n for n in d.notes), \
        f"peak cap handling: {d.chosen_offset} {d.notes}"
    # allcore pred 5018 > 5010: inverse on allcore curve -> between -5 (5002)
    # and -10 (5018): target 5010 -> offset -7.5, truncated toward zero -> -7
    # (conservative side of the cap); never deeper than the -20 boundary
    d = by_row2[3]
    assert d.chosen_offset == -7, f"allcore cap offset {d.chosen_offset}"
    assert d.freq_pred <= 5010 + 1

    # --- temp cap: 70 °C is below allcore temps even at the boundary -> warning
    report3 = derive_grid(tables, margin=10, max_temp=70, max_freq=0, max_voltage=0)
    assert any("temperature cap unreachable" in w for w in report3.warnings), \
        f"temp warnings: {report3.warnings}"

    # --- never-stable regime pins at the voltage cap ---
    broken = [r for r in tables if r['regime'] != "peak"]
    for off in (0, -5, -10, -15, -20, -25, -30):
        broken.append(row(off, "peak", 0, 0, False))
    report4 = derive_grid(broken, margin=10, max_temp=90, max_freq=0, max_voltage=0)
    d4 = {d.row: d for d in report4.regimes}[4]
    assert d4.chosen_offset == 0 and any("never stable" in n or "no stable" in n
                                         for n in d4.notes), d4.notes

    # --- crash residue: an unstable row SHALLOWER than a stable point
    # contradicts monotonicity and must be dropped (re-run after a crash) ---
    tables5 = tables + [row(-10, "allcore", 0, 0, False), row(-5, "allcore", 0, 0, False)]
    report5 = derive_grid(tables5, margin=10, max_temp=90, max_freq=0, max_voltage=0)
    d5 = {d.row: d for d in report5.regimes}[3]
    assert d5.deepest_stable == -20 and d5.first_unstable == -25, \
        f"crash residue not filtered: {d5.deepest_stable}/{d5.first_unstable}"
    assert d5.chosen_offset == -10

    print("derive smoke test: ALL ASSERTIONS PASSED")
    print("derived grid:")
    for r in report.grid:
        print("  ", r)
    print("warnings:", report.warnings)


if __name__ == "__main__":
    main()
