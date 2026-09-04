"""Offline regression tests for the v1.5.1 fixes (mocked hardware, no reboots).

Each test pins one confirmed defect so it cannot silently return:

  1. run_battery crashed with RuntimeError after EVERY battery window
     (TemperatureSampler stopped twice: context-manager exit + explicit call).
  2. attribute + calibrate interleaved with the classic per-cell search and
     measured the offset-0 level under the leftover +30 probe grid.
  3. A crashed attribution probe was consumed with zero windows re-run.
  4. "refine current grid" on a completed run exited before doing anything.
  5. Start on a cancelled reboot measured the old hardware state.
  6. A missing stress verdict (None) passed the stability gate (allcore/mid/low).
  7. A failing WHEA event-log query was silently treated as "0 errors".
  8. Derivation kept stale temp predictions after a freq-cap pullback and an
     ineffective-regime fallback.

Run:  python tests\\test_regressions.py
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import optimizer as om
import calibration as cal
import frequency_monitor as fm
import temperature_monitor as tm
import state_manager
from state_manager import OptimizationState
from config import CALIB_OFFSETS, CALIB_REGIMES, ATTRIBUTION_MAP

REGIME_OF_ROW = {v: k for k, v in ATTRIBUTION_MAP.items()}
BASE_FREQS = {"idle": 4500, "low": 4400, "mid": 4390, "allcore": 5000, "peak": 5400}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class SimpleProc:
    def poll(self):
        return None


class SimpleLoad:
    def __init__(self):
        self.procs = [SimpleProc()]

    def terminate(self):
        pass


class SimpleFreq:
    max_frequency = 5000.0


def redirect_state():
    """Send state load/save to a temp file; 'fake' dict injects a live state"""
    tmp = Path(tempfile.mkdtemp()) / "state.json"
    _orig_save = state_manager.OptimizationState.save
    _orig_load = state_manager.OptimizationState.load
    fake = {}
    state_manager.OptimizationState.save = lambda self, file_path=None: _orig_save(self, tmp)
    state_manager.OptimizationState.load = classmethod(
        lambda cls, file_path=None: fake.get('state') or _orig_load(cls, tmp))
    return fake


def battery_row(offset, probe, regime, freq, stable, temp):
    return {'offset': offset, 'probe': probe, 'regime': regime,
            'freq_max': freq, 'temp_max': temp, 'temp_avg': temp - 5,
            'temp_min': temp - 10, 'stable': stable, 'stress_verdict': stable,
            'whea': 0, 'n_temp_samples': 10, 'timestamp': 't'}


def mock_battery_hardware(events=None):
    """Stub every hardware-facing dependency of run_battery"""
    cal.ensure_throttle_100 = lambda: None
    cal.start_regime = lambda regime, duration: SimpleLoad()
    cal.sample_frequencies = lambda secs, tag: SimpleFreq()
    cal.check_whea_errors = lambda since=None: 0
    cal.CALIB_RAMPUP_SECONDS = 0
    tm.read_tctl = lambda: 55.0
    if events is not None:
        events['durations'] = dict(cal.REGIME_DURATIONS)
        cal.REGIME_DURATIONS.update({r: 0 for r in CALIB_REGIMES})


# ---------------------------------------------------------------------------
# 1. run_battery must survive the double TemperatureSampler.stop()
# ---------------------------------------------------------------------------

def test_battery_window_completes():
    mock_battery_hardware()
    cal._stress_verdict = lambda load, duration: True
    state = OptimizationState()
    state.calib_current_offset = 0
    state.calib_regime_index = 0
    rows = cal.run_battery(state)  # v1.5.0: RuntimeError('sampler was never started')
    assert len(rows) == 5, f"expected 5 windows, got {len(rows)}"
    assert all(r['stable'] for r in rows)
    assert all(r['temp_avg'] == 55.0 for r in rows), "temperature stats lost"
    print("  [1] run_battery completes all windows (double stop fixed)")


# ---------------------------------------------------------------------------
# 2. attribute + calibrate: clean handoff, no classic interleaving,
#    offset-0 measured exactly once (the attribution baseline)
# ---------------------------------------------------------------------------

def test_attribute_calibrate_pipeline():
    fake = redirect_state()
    events = {'batteries': [], 'cell_writes': [], 'grids': []}

    def fake_battery_session(self):
        st = self.state
        live = events['grids'][-1] if events['grids'] else st.current_grid
        offset = st.calib_current_offset or 0
        probe = st.attrib_probe_row
        events['batteries'].append({'grid': [r[:] for r in live],
                                    'offset': offset, 'probe': probe})
        if probe is not None:
            moved = REGIME_OF_ROW.get(probe)
            rows = [battery_row(offset, probe, r,
                                BASE_FREQS[r] + (400 if r == moved else 0), True, 60)
                    for r in CALIB_REGIMES]
        else:
            stable = offset >= -20
            freqs = dict(BASE_FREQS)
            freqs['allcore'] = 5000 + (-offset) * 2
            freqs['peak'] = 5400 + (-offset) * 3
            rows = [battery_row(offset, None, r,
                                freqs[r] if stable else 0.0, stable, 70)
                    for r in CALIB_REGIMES]
        st.calib_rows.extend(rows)
        st.status = "testing"
        st.calib_regime_index = 0
        return rows

    om.Optimizer._run_battery_session = fake_battery_session
    om.Optimizer._test_current_configuration = lambda self: {
        'grid': self.state.current_grid, 'stable': True, 'whea_errors': 0,
        'max_frequency': 5150.0, 'idle_freq': None, 'load_freq': None}
    om.cs_set_grid = lambda grid, force=True: events['grids'].append(
        [r[:] for r in grid])
    om.cs_set_cell = lambda *a, **k: events['cell_writes'].append(a)
    om.cs_clear = lambda force=True: None
    cal.cs_set_grid = om.cs_set_grid  # stage_calibration_offset / stage_attribution_grid

    state = OptimizationState()
    state.mode = "attribute"
    state.caps = {'max_temp': 90.0, 'max_freq': 0.0, 'max_voltage': 0, 'margin': 10}
    fake['state'] = state

    reboots = 0
    results = None
    for _boot in range(25):
        opt = om.Optimizer()
        try:
            results = opt.run()
            break
        except SystemExit:
            reboots += 1
            st = OptimizationState.load()
            assert st.status == "waiting_reboot"
            st.status = "testing"
            st.save()
    else:
        raise AssertionError("attribute+calibrate run did not finish in 25 boots")

    assert results and results['status'] == "completed", results['status']
    assert results['mode'] == "standard"
    # 13 staging exits: baseline + 5 probes + 6 levels + final validation;
    # the 14th boot runs the validation and returns without a SystemExit
    assert reboots == 13, f"expected 13 staging reboots, got {reboots}"
    assert not events['cell_writes'], \
        f"classic per-cell search interleaved: {events['cell_writes']}"

    natural_zero = [b for b in events['batteries']
                    if b['probe'] is None and b['offset'] == 0]
    assert len(natural_zero) == 1, \
        f"offset-0 battery ran {len(natural_zero)}x (baseline + leftover probe grid?)"
    assert natural_zero[0]['grid'] == [[0] * 3] * 5, "baseline not measured under the 0 grid"

    probe_batteries = [b for b in events['batteries'] if b['probe'] is not None]
    assert len(probe_batteries) == 5
    for b in probe_batteries:
        row = b['probe']
        assert b['grid'][row] == [30, 30, 30], f"probe row {row} grid {b['grid'][row]}"
        assert sum(1 for r in b['grid'] if r == [0, 0, 0]) == 4

    sweeps = [b for b in events['batteries'] if b['probe'] is None and b['offset'] != 0]
    assert [b['offset'] for b in sweeps] == CALIB_OFFSETS[1:], \
        f"sweep levels {[b['offset'] for b in sweeps]}"
    for b in sweeps:
        assert all(r == [b['offset']] * 3 for r in b['grid']), \
            f"level {b['offset']} measured under grid {b['grid']}"

    assert results['derived_grid'] == [[-10] * 3 for _ in range(5)]
    assert len(results['calibration_levels_done']) == 7
    print(f"  [2] attribute+calibrate clean ({reboots} reboots, offset-0 measured once)")


# ---------------------------------------------------------------------------
# 3. crashed probe battery: re-run from window 0, not consumed with 0 data
# ---------------------------------------------------------------------------

def test_probe_crash_reruns_battery():
    fake = redirect_state()
    batteries = []
    grids = []

    def fake_battery_session(self):
        st = self.state
        batteries.append({'from_index': st.calib_regime_index,
                          'probe': st.attrib_probe_row})
        moved = REGIME_OF_ROW.get(st.attrib_probe_row)
        rows = [battery_row(0, st.attrib_probe_row, r,
                            BASE_FREQS[r] + (400 if r == moved else 0), True, 60)
                for r in CALIB_REGIMES]
        st.calib_rows.extend(rows)
        st.status = "testing"
        st.calib_regime_index = 0
        return rows

    om.Optimizer._run_battery_session = fake_battery_session
    om.cs_set_cell = lambda *a, **k: None
    om.cs_set_grid = lambda grid, force=True: grids.append(grid)
    cal.cs_set_grid = om.cs_set_grid

    state = OptimizationState()
    state.mode = "attribute"
    state.calib_baseline = [{'regime': r, 'freq_max': BASE_FREQS[r]} for r in CALIB_REGIMES]
    state.attrib_rows_done = [0, 1]
    state.attrib_probe_row = 2          # crashed during row 2's battery
    state.calib_current_offset = 0
    state.calib_regime_index = 2
    state.status = "battery_running"    # as a mid-battery crash leaves it:
                                        # run() credits the remaining windows
                                        # unstable, then _attribute_step must
                                        # reset the index and re-run the probe
    fake['state'] = state

    opt = om.Optimizer()
    try:
        opt.run()
        raise AssertionError("expected SystemExit (next probe staged)")
    except SystemExit:
        pass

    assert batteries and batteries[0]['from_index'] == 0, \
        f"probe battery not re-run from window 0: {batteries}"
    assert 2 in state.attrib_rows_done
    assert state.attrib_probe_row == 3 and grids[-1][3] == [30, 30, 30], \
        "next probe (row 3) was not staged"
    print("  [3] crashed probe re-runs its battery and staging continues")


# ---------------------------------------------------------------------------
# 4. refine current grid on a completed run must actually start searching
# ---------------------------------------------------------------------------

def test_refine_on_completed_runs():
    fake = redirect_state()
    cell_calls = []
    om.cs_set_cell = lambda *a, **k: cell_calls.append(a)
    om.cs_set_grid = lambda *a, **k: None
    om.cs_clear = lambda force=True: None

    state = OptimizationState()
    state.mode = "standard"
    state.status = "completed"
    state.current_phase = "completed"
    state.iteration = 1
    state.total_reboots = 8
    state.derived_grid = [[-10] * 3 for _ in range(5)]
    state.current_grid = [[-10] * 3 for _ in range(5)]
    state.seed_full_refinement()        # what the GUI's refine mode does
    fake['state'] = state

    opt = om.Optimizer()
    try:
        opt.run()
        raise AssertionError("expected SystemExit (first cell staged)")
    except SystemExit:
        pass
    assert cell_calls, "refinement never staged a cell (silent no-op)"
    assert state.status == "waiting_reboot"
    print("  [4] refine current grid starts the search on a completed run")


# ---------------------------------------------------------------------------
# 5. Start without a reboot since staging must refuse (stale grid protection)
# ---------------------------------------------------------------------------

def test_reboot_required_guard():
    fake = redirect_state()
    om.cs_set_cell = lambda *a, **k: None
    om.cs_clear = lambda force=True: None
    om.POST_BOOT_DELAY = 0
    real_uptime = state_manager._uptime_seconds

    state = OptimizationState()
    state.mode = "standard"
    state.status = "waiting_reboot"
    state.staged_uptime_s = real_uptime() - 10   # staged 10 s ago, machine still up
    fake['state'] = state

    opt = om.Optimizer()
    try:
        opt.run()
        raise AssertionError("expected RebootRequired")
    except om.RebootRequired:
        pass
    assert state.status == "waiting_reboot", \
        f"status clobbered to {state.status!r} — resume after the reboot would break"

    # after a real reboot the uptime resets below the staged value -> proceed
    state_manager._uptime_seconds = lambda: 0.5
    try:
        try:
            opt.run()
            raise AssertionError("expected SystemExit (baseline staged)")
        except SystemExit:
            pass
    finally:
        state_manager._uptime_seconds = real_uptime
    print("  [5] stale staged grid refused until the machine actually reboots")


# ---------------------------------------------------------------------------
# 6. missing stress verdict fails closed for gated regimes
# ---------------------------------------------------------------------------

def test_stress_verdict_gate():
    mock_battery_hardware()
    cal._stress_verdict = lambda load, duration: None   # killed, no usable verdict
    state = OptimizationState()
    state.calib_current_offset = 0
    state.calib_regime_index = 0
    rows = cal.run_battery(state)
    by = {r['regime']: r for r in rows}
    assert by['idle']['stable'], "idle window must not depend on a verdict"
    assert by['peak']['stable'], "peak window must not depend on a verdict"
    assert not by['allcore']['stable'], "missing verdict passed the all-core gate"
    assert not by['mid']['stable'] and not by['low']['stable']
    print("  [6] missing stress verdict fails closed (allcore/mid/low)")


# ---------------------------------------------------------------------------
# 7. WHEA query failure raises instead of pretending "0 errors"
# ---------------------------------------------------------------------------

def test_whea_query_failure_raises():
    failing = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")
    fm.run_command = lambda cmd, check=False: failing
    try:
        fm.check_whea_errors()
        raise AssertionError("expected MeasurementError on query failure")
    except fm.MeasurementError:
        pass

    empty = subprocess.CompletedProcess(args=[], returncode=0, stdout="\n", stderr="")
    fm.run_command = lambda cmd, check=False: empty
    assert fm.check_whea_errors() == 0, "no events (empty output) must read 0"

    zero = subprocess.CompletedProcess(args=[], returncode=0, stdout="0\n", stderr="")
    fm.run_command = lambda cmd, check=False: zero
    assert fm.check_whea_errors() == 0
    print("  [7] WHEA query failure raises MeasurementError (fail closed)")


# ---------------------------------------------------------------------------
# 8. derivation: predictions follow the offset the solver actually chose
# ---------------------------------------------------------------------------

def _row(regime, offset, freq, temp, stable):
    return {'offset': offset, 'regime': regime, 'freq_max': freq,
            'temp_max': temp, 'stable': stable}


def test_derive_preds_follow_chosen_offset():
    from derive import derive_grid

    rows = []
    # allcore: deepest stable -10 -> chosen 0 (margin 10, cap 0), pred 5000
    for off, f, t, s in [(0, 5000, 70, True), (-5, 5010, 72, True),
                         (-10, 5020, 74, True), (-15, 0, 0, False),
                         (-20, 0, 0, False), (-25, 0, 0, False), (-30, 0, 0, False)]:
        rows.append(_row("allcore", off, f, t, s))
    # low: looks like allcore (ineffective throttle) but stable to -15, so its
    # own chosen (-5) differs from the all-core fallback (0)
    for off, f, t in [(0, 4990, 60), (-5, 4995, 61), (-10, 4998, 62), (-15, 4999, 63)]:
        rows.append(_row("low", off, f, t, True))
    rows.append(_row("low", -20, 0, 0, False))
    # peak with a freq cap: chosen pulled back along the curve
    for off, f, t, s in [(0, 5400, 55, True), (-5, 5420, 57, True),
                         (-10, 5430, 59, True), (-15, 0, 0, False)]:
        rows.append(_row("peak", off, f, t, s))

    report = derive_grid(rows, attribution={"idle": 0, "low": 1, "mid": 2,
                                            "allcore": 3, "peak": 4},
                         margin=10, max_temp=90, max_freq=0, max_voltage=0)
    d = {x.regime: x for x in report.regimes}
    assert d['low'].effective is False
    assert d['low'].chosen_offset == 0
    assert d['low'].freq_pred == 4990, \
        f"fallback pred {d['low'].freq_pred} — still interpolated at the old offset (-5)"

    capped = derive_grid(rows, attribution={"idle": 0, "low": 1, "mid": 2,
                                            "allcore": 3, "peak": 4},
                         margin=0, max_temp=90, max_freq=5415, max_voltage=0)
    dp = {x.regime: x for x in capped.regimes}
    # peak curve (-10,5430) (-5,5420) (0,5400): target 5415 lands between -5
    # and 0 -> offset -3 (int(-3.75), truncated toward zero so freq <= cap)
    assert dp['peak'].chosen_offset == -3, \
        f"peak cap offset {dp['peak'].chosen_offset} (expected pullback to -3)"
    assert dp['peak'].freq_pred <= 5415 + 1
    assert abs(dp['peak'].temp_pred - 56.2) < 0.01, \
        f"temp_pred {dp['peak'].temp_pred} — not recomputed at the capped offset (-3)"
    print("  [8] derive predictions recomputed after cap pullback and fallback")


def main():
    print("regression tests:")
    test_battery_window_completes()
    test_attribute_calibrate_pipeline()
    test_probe_crash_reruns_battery()
    test_refine_on_completed_runs()
    test_reboot_required_guard()
    test_stress_verdict_gate()
    test_whea_query_failure_raises()
    test_derive_preds_follow_chosen_offset()
    print("ALL REGRESSION TESTS PASSED")


if __name__ == "__main__":
    main()
