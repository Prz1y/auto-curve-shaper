"""Offline orchestration smoke test: drives Optimizer through the full
calibrate -> derive -> verify pipeline with mocked hardware access.

No probe calls, no reboots, no state.json in the project directory
(redirected to a temp file). Run:  python tests\\test_pipeline.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import state_manager
import optimizer as optimizer_mod
import calibration as calibration_mod
from config import CALIB_OFFSETS, CALIB_REGIMES
from state_manager import OptimizationState

TMP_STATE = Path(tempfile.mkdtemp()) / "state.json"

_orig_save = OptimizationState.save
_orig_load = OptimizationState.load

OptimizationState.save = lambda self, file_path=None: _orig_save(self, TMP_STATE)
# _orig_load was captured as a bound classmethod (cls already bound)
OptimizationState.load = classmethod(lambda cls, file_path=None: _orig_load(TMP_STATE))

_staged_grids = []


def fake_cs_set_grid(grid, force=True):
    _staged_grids.append([row[:] for row in grid])


# --- synthetic calibration data: allcore/peak/mid break below -20, idle holds
def fake_run_battery(state):
    offset = state.calib_current_offset
    state.calib_regime_index = len(CALIB_REGIMES)  # run_battery leaves index past end
    stable = offset >= -20
    freqs = {"idle": 4500, "low": 4400, "mid": 4390, "allcore": 5000 + (-offset) * 2,
             "peak": 5400 + (-offset) * 3}
    temps = {"idle": 45, "low": 60, "mid": 58, "allcore": 75, "peak": 60}
    rows = [{'offset': offset, 'probe': None, 'regime': r,
             'freq_max': freqs[r] if stable else 0.0,
             'temp_max': temps[r], 'temp_avg': temps[r] - 5, 'temp_min': temps[r] - 10,
             'stable': stable, 'stress_verdict': True if stable else False,
             'whea': 0, 'n_temp_samples': 10, 'timestamp': "t"} for r in CALIB_REGIMES]
    state.calib_rows.extend(rows)  # real run_battery persists rows itself
    return rows


def fake_test_current_configuration(self):
    return {'grid': self.state.current_grid, 'stable': True, 'whea_errors': 0,
            'max_frequency': 5150.0, 'idle_freq': None, 'load_freq': None}


optimizer_mod.cs_set_grid = fake_cs_set_grid
optimizer_mod.cs_set_cell = lambda *a, **k: None
optimizer_mod.cs_clear = lambda force=True: None
calibration_mod.cs_set_grid = fake_cs_set_grid  # stage_calibration_offset's binding
optimizer_mod.run_battery = fake_run_battery
optimizer_mod.Optimizer._test_current_configuration = fake_test_current_configuration

MAX_STEPS = 40


def main():
    state = OptimizationState()
    state.mode = "calibrate"
    state.caps = {'max_temp': 90.0, 'max_freq': 0.0, 'max_voltage': 0, 'margin': 10}
    state.save()

    reboots = 0
    results = None
    for step in range(MAX_STEPS):
        opt = optimizer_mod.Optimizer()
        try:
            results = opt.run()
            break  # ran to completion
        except SystemExit:
            reboots += 1
            # simulate the reboot: staged grid goes live at next logon
            state = OptimizationState.load()
            assert state.status == "waiting_reboot", f"step {step}: status {state.status}"
            state.status = "testing"
            state.save()
    else:
        raise AssertionError(f"pipeline did not finish within {MAX_STEPS} steps")

    assert results is not None and results['status'] == "completed", results
    assert results['mode'] == "standard", results['mode']
    assert len(results['calibration_levels_done']) == len(CALIB_OFFSETS)

    grid = results['derived_grid']
    # boundaries at -20, margin 10 -> -10 everywhere
    assert grid == [[-10] * 3 for _ in range(5)], f"derived grid {grid}"

    # one staged grid per calibration level + one for final validation
    assert len(_staged_grids) == len(CALIB_OFFSETS) + 1, len(_staged_grids)
    assert _staged_grids[0] == [[0] * 3 for _ in range(5)]
    assert _staged_grids[-1] == grid

    assert reboots == len(CALIB_OFFSETS) + 1, f"reboots {reboots}"

    state = OptimizationState.load()
    assert state.status == "completed"
    assert state.derive_report['peak_freq_pred_mhz'] > 0

    # --- crash-resume: mid-battery death credits remaining windows unstable ---
    state2 = OptimizationState()
    state2.mode = "calibrate"
    state2.caps = state.caps
    state2.save()
    from calibration import mark_crash_remaining
    state2.calib_current_offset = -5
    state2.calib_regime_index = 2  # crashed during the 3rd window
    state2.save()
    n = mark_crash_remaining(state2, "test crash")
    assert n == len(CALIB_REGIMES) - 2
    assert all(not r['stable'] for r in state2.calib_rows)
    assert state2.calib_regime_index == len(CALIB_REGIMES)

    print(f"pipeline smoke test: PASSED ({reboots} reboots, grid {grid})")


if __name__ == "__main__":
    main()
