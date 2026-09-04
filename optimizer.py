# SPDX-License-Identifier: GPL-3.0-or-later
"""
Core optimization engine
"""
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

from config import (
    INITIAL_OFFSET, MIN_SAFE_OFFSET,
    IDLE_SAMPLE_DURATION, LOAD_SAMPLE_DURATION,
    STABILITY_TEST_DURATION, CS_ROWS, CS_COLS,
    ROW_NAMES, COL_NAMES, MAX_REBOOT_ATTEMPTS, MAX_SWEEPS,
    ATTRIBUTION_MAP, ATTRIB_PROBE_ROWS, CALIB_MARGIN, CALIB_OFFSETS,
    CALIB_REGIMES, MAX_TEMP_LIMIT, MAX_FREQ_LIMIT, MAX_VOLTAGE_OFFSET,
)
from state_manager import OptimizationState, RebootManager
from frequency_monitor import (
    measure_frequencies_idle,
    measure_frequencies_load,
    run_stability_test,
    check_whea_errors
)
from utils import cs_set_grid, cs_clear, cs_set_cell
from calibration import (
    run_battery, mark_crash_remaining, stage_calibration_offset,
    stage_attribution_grid, compute_attribution,
)
from derive import derive_grid

# Refinement sweeps count a cell as "changed" only when its optimum moves by
# more than this many steps; ±1 binary-search jitter must not trigger another
# sweep (otherwise the search never converges: the seeded search always probes
# one step beyond the previous result)
CONVERGENCE_DEADBAND = 2

logger = logging.getLogger(__name__)


class Optimizer:
    """Main optimization engine"""
    
    def __init__(self):
        self.reboot_mgr = RebootManager()
        self.state: Optional[OptimizationState] = None
    
    def run(self) -> Dict[str, Any]:
        """
        Main optimization loop
        Returns final results
        """
        # Initialize or restore state
        self.state = self.reboot_mgr.initialize()

        # A previous run may have failed mid-test (power loss, workload
        # hiccup, fixed bug). An explicit start means "continue": the staged
        # cell/search state is intact, so retry from where it stopped.
        if self.state.status == "failed":
            logger.warning(f"Previous run failed ({self.state.error_message!r}) — "
                           f"retrying from saved position")
            self.state.status = "testing"
            self.state.error_message = ""
            self.state.save()

        # Check if we just rebooted
        if self.state.status == "waiting_reboot":
            logger.info("Detected post-reboot state, continuing optimization...")
            self.reboot_mgr.after_reboot()
            time.sleep(5)  # Brief delay after boot

        # A session that died mid-battery (crash/panic under the staged grid)
        # keeps the "battery_running" status: the windows that never ran are
        # credited as UNSTABLE for the staged offset, then the pipeline moves on
        if self.state.status == "battery_running":
            mark_crash_remaining(self.state, "session crashed mid-battery")
            self.state.status = "testing"
            self.state.save()

        # Check if we should continue
        if not self.reboot_mgr.should_continue(MAX_REBOOT_ATTEMPTS):
            return self._generate_final_report()

        # Main optimization loop
        try:
            # v1.5 pipeline: attribution experiment and calibration sweep.
            # Each step may raise SystemExit to reboot; when a phase completes
            # it falls through (or hands over) to the standard loop below.
            if self.state.mode == "attribute":
                self._attribute_step()
            if self.state.mode == "calibrate":
                self._calibrate_step()

            # Final validation, phase B: the converged/derived grid was staged
            # and rebooted in; now actually test it before declaring completion
            if self.state.current_phase == "final_validation":
                self._complete_final_validation()
                return self._generate_final_report()

            if self.state.iteration == 0 and self.state.mode == "standard" \
                    and self.state.derived_grid is None and not self.state.calib_rows:
                # First run of a classic search: establish baseline
                logger.info("=== Starting Optimization: Baseline Measurement ===")
                self._run_baseline()

            # Seed the queue on a fresh run, or when resuming a pre-1.2 state
            # (sweep 1, queue empty, cells still unoptimized). Otherwise trust
            # the persisted queue: refilling an exhausted refinement queue on
            # every session would re-add cells forever and the sweep boundary
            # would never be reached across sessions
            if self.state.sweep == 1 and not self.state.sweep_remaining \
                    and len(self.state.cells_optimized) < CS_ROWS * CS_COLS:
                self._refill_sweep_queue()

            # Optimize cells sweep by sweep: shaper fields overlap, so after
            # the first pass the grid is re-searched until a full sweep
            # changes nothing (or MAX_SWEEPS is reached)
            while not self.state.converged:
                if not self.reboot_mgr.should_continue(MAX_REBOOT_ATTEMPTS):
                    break

                if not self.state.sweep_remaining:
                    if not self._advance_sweep():
                        break
                    continue

                self._optimize_next_cell()
            
            # Final test with best configuration
            logger.info("=== Optimization Complete: Final Validation ===")
            self._run_final_validation()
            
            self.state.status = "completed"
            self.state.save()
            
            return self._generate_final_report()
            
        except KeyboardInterrupt:
            logger.warning("Optimization interrupted by user")
            self.state.status = "interrupted"
            self.state.save()
            return self._generate_final_report()
        
        except Exception as e:
            logger.error(f"Optimization failed: {e}", exc_info=True)
            self.state.status = "failed"
            self.state.error_message = str(e)
            self.state.save()
            raise
    
    def _run_baseline(self) -> None:
        """Run baseline measurements with all offsets at 0"""
        logger.info("Clearing all CS cells for baseline...")
        cs_clear(force=True)
        
        # Set state
        self.state.current_grid = [[0] * CS_COLS for _ in range(CS_ROWS)]
        self.state.status = "running"
        self.state.current_phase = "baseline"
        self.state.iteration = 1
        self.state.save()
        
        # Trigger reboot
        logger.info("Baseline configuration staged. A reboot applies it.")
        logger.info("Waiting for the reboot to complete before testing.")

        self.reboot_mgr.prepare_for_reboot()

        raise SystemExit("Baseline staged. A reboot is required to apply it.")

    # ------------------------------------------------------------------
    # v1.5 pipeline steps
    # ------------------------------------------------------------------

    def _reboot_exit(self, reason: str) -> None:
        """Persist state and hand control to the GUI's reboot countdown"""
        logger.info(f"{reason} Rebooting to apply.")
        self.reboot_mgr.prepare_for_reboot()
        raise SystemExit(reason)

    def _run_battery_session(self) -> List[dict]:
        """Run the full-spectrum battery for the currently staged grid"""
        self.state.status = "battery_running"
        self.state.save()
        rows = run_battery(self.state)
        self.state.status = "testing"
        self.state.calib_regime_index = 0
        self.state.save()
        return rows

    def _attribute_step(self) -> None:
        """Differential attribution experiment: one CS row +30 per reboot.

        Establishes the offset-0 battery first (also the calibration
        baseline), then probes each row and records which regimes respond.
        Regimes the experiment never attributes keep the config default map.
        """
        # Phase 1: baseline battery at offset 0
        if not self.state.calib_baseline:
            if self.state.calib_current_offset != 0:
                self.state.attrib_probe_row = None
                self.state.save()
                stage_calibration_offset(self.state, 0)
                self._reboot_exit("Attribution baseline (offset 0) staged")
            if self.state.calib_regime_index >= len(CALIB_REGIMES):
                # crash residue: those windows were already credited unstable;
                # re-run the battery so the baseline holds real measurements
                self.state.calib_regime_index = 0
            if self.state.calib_regime_index == 0:
                rows = self._run_battery_session()
                self.state.calib_baseline = [r for r in rows if r['offset'] == 0]
                self.state.save()
                logger.info(f"Attribution baseline recorded ({len(self.state.calib_baseline)} windows)")

        # Phase 2: probe rows one at a time
        if self.state.attributed_map is None:
            self.state.attributed_map = {}

        probe = next((r for r in ATTRIB_PROBE_ROWS if r not in self.state.attrib_rows_done), None)
        if probe is None:
            logger.info("=== Attribution experiment complete ===")
            for regime, row in sorted(self.state.attributed_map.items()):
                logger.info(f"  {regime:8s} -> {ROW_NAMES[row]} row")
            self.state.mode = "calibrate"
            self.state.save()
            return

        if self.state.attrib_probe_row != probe:
            stage_attribution_grid(probe)
            self.state.attrib_probe_row = probe
            self.state.calib_current_offset = 0  # base grid is all-zero + one probed row
            self.state.save()
            self._reboot_exit(f"Attribution probe for {ROW_NAMES[probe]} row (+30) staged")

        rows = self._run_battery_session()
        merged = compute_attribution(self.state.calib_baseline, rows, probe)
        for regime, row in merged.items():
            self.state.attributed_map.setdefault(regime, row)
        self.state.attrib_rows_done.append(probe)
        self.state.attrib_probe_row = None
        self.state.save()

    def _calibrate_step(self) -> None:
        """Uniform-grid offset sweep: one reboot per level, full battery each"""
        while True:
            if self.state.calib_current_offset is None:
                stage_calibration_offset(self.state, CALIB_OFFSETS[0])
                self._reboot_exit(f"First calibration level ({CALIB_OFFSETS[0]:+d}) staged")

            if self.state.calib_regime_index >= len(CALIB_REGIMES):
                # crash residue: those windows were already credited unstable;
                # re-run the battery so this level also has real measurements
                self.state.calib_regime_index = 0

            self._run_battery_session()
            if self.state.calib_current_offset not in self.state.calib_offsets_done:
                self.state.calib_offsets_done.append(self.state.calib_current_offset)
            self.state.save()
            logger.info(f"Calibration level {self.state.calib_current_offset:+d} complete "
                        f"({len(self.state.calib_offsets_done)}/{len(CALIB_OFFSETS)} levels)")

            done = set(self.state.calib_offsets_done)
            next_offset = next((o for o in CALIB_OFFSETS if o not in done), None)
            if next_offset is None:
                self._finalize_derivation()
                return
            stage_calibration_offset(self.state, next_offset)
            self._reboot_exit(f"Calibration level {next_offset:+d} staged")

    def _finalize_derivation(self) -> None:
        """Sweep complete: fit boundaries, apply caps, seed verification"""
        attribution = {**ATTRIBUTION_MAP, **(self.state.attributed_map or {})}
        caps = self.state.caps or {}
        report = derive_grid(
            self.state.calib_rows,
            attribution=attribution,
            margin=caps.get('margin', CALIB_MARGIN),
            max_temp=caps.get('max_temp', MAX_TEMP_LIMIT),
            max_freq=caps.get('max_freq', MAX_FREQ_LIMIT),
            max_voltage=caps.get('max_voltage', MAX_VOLTAGE_OFFSET),
        )

        self.state.derived_grid = report.grid
        self.state.derive_report = report.as_dict()
        self.state.iteration += 1

        logger.info("=== Calibration sweep complete: derivation ===")
        for d in report.regimes:
            logger.info(f"  {ROW_NAMES[d.row]:5s} <- {d.regime:8s} offset {d.chosen_offset:+d} "
                        f"(boundary {d.deepest_stable}, pred {d.freq_pred:.0f} MHz / "
                        f"{d.temp_pred:.0f} °C)"
                        + (" [!]" if d.notes else ""))
        for w in report.warnings:
            logger.warning(f"  derivation: {w}")
        logger.info("Derived grid:")
        for row_idx, row in enumerate(report.grid):
            logger.info(f"  {ROW_NAMES[row_idx]:5s}: {[f'{v:+d}' for v in row]}")

        # Hand over to the standard loop in verify-only mode: empty sweep
        # queue + sweep 2 goes straight to final validation, which now really
        # reboots into the derived grid and tests it
        self.state.seed_verify_from_grid(report.grid)
        self.state.save()
    
    def _optimize_next_cell(self) -> None:
        """Optimize the next cell in the sequence"""
        # Check if we're continuing an existing search
        if self.state.current_cell is not None:
            row, col = self.state.current_cell
            logger.info(f"\n=== Continuing Cell [{ROW_NAMES[row]}, {COL_NAMES[col]}] Optimization - Iteration {self.state.iteration} ===")
            
            # Continue binary search
            optimal_offset = self._continue_binary_search(row, col)
            
            if optimal_offset is not None:
                # Search completed
                prev_value = self.state.current_grid[row][col]
                self.state.mark_cell_optimized(row, col, optimal_offset)
                # Sync hardware: the last TESTED value (often an unstable one)
                # must not linger while subsequent cells are tested
                cs_set_cell(row, col, optimal_offset, force=True)
                self.state.current_cell = None
                if self.state.sweep >= 2 and abs(optimal_offset - prev_value) > CONVERGENCE_DEADBAND:
                    self.state.sweep_changes += 1
                    logger.info(f"Refinement changed this cell: {prev_value:+d} -> {optimal_offset:+d}")
                self.state.save()
                logger.info(f"Cell [{ROW_NAMES[row]}, {COL_NAMES[col]}] optimization complete: {optimal_offset:+d}")
            else:
                # Need to continue (will reboot)
                pass
            
            return
        
        # Get next cell to optimize
        next_cell = self.state.get_next_cell_to_optimize()
        
        if next_cell is None:
            logger.info("All cells optimized!")
            return
        
        row, col = next_cell
        self.state.current_cell = next_cell
        self.state.iteration += 1
        
        logger.info(f"\n=== Starting Cell [{ROW_NAMES[row]}, {COL_NAMES[col]}] Optimization - Iteration {self.state.iteration} ===")
        
        # Start binary search for optimal offset
        self._start_binary_search(row, col)

    def _refill_sweep_queue(self, force: bool = False) -> None:
        """Populate the current sweep's cell queue if it is empty"""
        if self.state.sweep_remaining and not force:
            return
        order = self.state.optimization_order()
        if self.state.sweep == 1:
            # First sweep (also covers state migrated from older versions):
            # only cells that have never been optimized
            self.state.sweep_remaining = [c for c in order if c not in self.state.cells_optimized]
        else:
            # Refinement sweeps re-visit every cell
            self.state.sweep_remaining = list(order)
        self.state.save()

    def _advance_sweep(self) -> bool:
        """Called when the current sweep's queue is empty.

        Returns True if another sweep was queued, False if the search is done.
        """
        if self.state.sweep == 1:
            logger.info("=== Sweep 1 complete: starting refinement sweep 2 ===")
            self.state.sweep = 2
            self.state.sweep_changes = 0
            self._refill_sweep_queue(force=True)
            return True

        if self.state.sweep_changes == 0:
            logger.info(f"=== Sweep {self.state.sweep} changed nothing: search converged ===")
            self.state.converged = True
            self.state.save()
            return False

        if self.state.sweep >= MAX_SWEEPS:
            logger.info(f"=== MAX_SWEEPS ({MAX_SWEEPS}) reached: stopping with current values ===")
            self.state.converged = True
            self.state.save()
            return False

        logger.info(f"=== Sweep {self.state.sweep} changed {self.state.sweep_changes} cell(s): "
                    f"starting sweep {self.state.sweep + 1} ===")
        self.state.sweep += 1
        self.state.sweep_changes = 0
        self._refill_sweep_queue(force=True)
        return True
    
    def _start_binary_search(self, row: int, col: int) -> None:
        """
        Start binary search for optimal offset for a single cell
        """
        # Initialize search range; best_stable_offset MUST be reset here,
        # otherwise the next cell inherits the previous cell's optimum
        self.state.search_min = MIN_SAFE_OFFSET  # -30
        self.state.search_max = 0  # No positive voltage for max frequency strategy
        self.state.best_stable_offset = 0
        if self.state.sweep >= 2:
            # Refinement sweep: seed from the previous optimum so the search
            # spends its reboots exploring below it instead of re-finding it
            self.state.search_current = self.state.current_grid[row][col]
            logger.info(f"Refinement sweep {self.state.sweep}: seeding from previous optimum {self.state.search_current:+d}")
        else:
            self.state.search_current = INITIAL_OFFSET  # -5
        
        logger.info(f"Starting binary search: range [{self.state.search_min}, {self.state.search_max}], initial offset {self.state.search_current:+d}")
        
        # Apply initial offset to grid
        test_grid = [row_data[:] for row_data in self.state.current_grid]  # Copy current grid
        test_grid[row][col] = self.state.search_current
        
        # Apply to hardware
        cs_set_cell(row, col, self.state.search_current, force=True)
        self.state.current_grid = test_grid
        self.state.save()
        
        # Trigger reboot
        logger.info("Initial configuration set. Rebooting to apply changes...")
        self.reboot_mgr.prepare_for_reboot()
        
        raise SystemExit("Configuration staged. A reboot is required to apply it.")
    
    def _continue_binary_search(self, row: int, col: int) -> Optional[int]:
        """
        Continue binary search after reboot
        Returns the optimal offset when search is complete, None if more testing needed
        """
        # Run test on current configuration
        logger.info(f"Testing offset {self.state.search_current:+d}...")
        result = self._test_current_configuration()
        
        # Determine if current offset is stable
        is_stable = (result.get('stable', False) and
                    result.get('whea_errors', 0) == 0 and
                    result.get('max_frequency', 0) > 0)

        if is_stable:
            logger.info(f"Offset {self.state.search_current:+d} is STABLE (freq: {result['max_frequency']:.0f} MHz)")
            
            # Update best stable offset
            if self.state.search_current < self.state.best_stable_offset:
                self.state.best_stable_offset = self.state.search_current
                logger.info(f"New best stable offset: {self.state.best_stable_offset:+d}")
            
            # Try more aggressive (lower) offset
            self.state.search_max = self.state.search_current
        else:
            logger.warning(f"Offset {self.state.search_current:+d} is UNSTABLE")
            
            # Back off to safer offset
            self.state.search_min = self.state.search_current
        
        # Check if search has converged
        if self.state.search_max - self.state.search_min <= 1:
            logger.info(f"Binary search converged! Optimal offset: {self.state.best_stable_offset:+d}")
            return self.state.best_stable_offset
        
        # Calculate next test point (midpoint)
        next_offset = (self.state.search_min + self.state.search_max) // 2
        self.state.search_current = next_offset
        self.state.iteration += 1
        
        logger.info(f"Next test: offset {next_offset:+d}, range [{self.state.search_min}, {self.state.search_max}]")
        
        # Apply next offset to grid
        test_grid = [row_data[:] for row_data in self.state.current_grid]
        test_grid[row][col] = next_offset
        
        # Apply to hardware
        cs_set_cell(row, col, next_offset, force=True)
        self.state.current_grid = test_grid
        self.state.save()
        
        # Trigger reboot
        logger.info("Next configuration set. Rebooting to apply changes...")
        self.reboot_mgr.prepare_for_reboot()
        
        raise SystemExit("Configuration staged. A reboot is required to apply it.")
    
    def _test_current_configuration(self) -> Dict[str, Any]:
        """
        Test current configuration and return results.

        Measurement infrastructure failures (MeasurementError, timeouts,
        missing tools) propagate as exceptions and fail the run — they must
        not be mistaken for an unstable configuration.
        """
        logger.info("Testing current configuration...")

        result = {
            'grid': [row[:] for row in self.state.current_grid],
            'timestamp': datetime.now().isoformat()
        }

        # WHEA errors since the last poll: covers the config apply, reboot
        # and boot of the configuration currently under test
        whea_count = check_whea_errors(self._last_whea_check_dt())
        self.state.last_whea_check = datetime.now().isoformat()
        result['whea_errors'] = whea_count

        if whea_count > 0:
            logger.warning(f"WHEA errors detected: {whea_count} - configuration is unstable")
            result['stable'] = False
            result['idle_freq'] = None
            result['load_freq'] = None
            result['max_frequency'] = 0.0
            self.state.record_test_result(result)
            self.state.save()
            return result

        # Measure idle frequencies
        idle_measurement = measure_frequencies_idle(IDLE_SAMPLE_DURATION)
        result['idle_freq'] = {
            'ccd0': idle_measurement.ccd0_freq,
            'ccd1': idle_measurement.ccd1_freq,
            'avg': idle_measurement.avg_frequency,
            'max': idle_measurement.max_frequency,
            'all_cores': idle_measurement.all_cores
        }

        # Measure load frequencies
        load_measurement = measure_frequencies_load(LOAD_SAMPLE_DURATION)
        result['load_freq'] = {
            'ccd0': load_measurement.ccd0_freq,
            'ccd1': load_measurement.ccd1_freq,
            'avg': load_measurement.avg_frequency,
            'max': load_measurement.max_frequency,
            'all_cores': load_measurement.all_cores
        }

        # For max frequency target, use max load frequency
        result['max_frequency'] = load_measurement.max_frequency

        # Quick stability test
        stable = run_stability_test(STABILITY_TEST_DURATION)

        # WHEA errors generated during the stress test itself are attributed
        # to THIS configuration, not left for the next test to find
        post_whea = check_whea_errors(self._last_whea_check_dt())
        self.state.last_whea_check = datetime.now().isoformat()
        result['whea_errors'] += post_whea

        if post_whea > 0:
            logger.warning(f"{post_whea} WHEA errors during stability test - configuration is unstable")
            stable = False

        result['stable'] = stable

        if not stable:
            logger.warning("Stability test failed")
            result['max_frequency'] = 0.0  # Unstable config gets 0 score

        # Record result
        self.state.record_test_result(result)
        self.state.save()

        logger.info(f"Test result: Max Freq = {result['max_frequency']:.0f} MHz, Stable = {result['stable']}")

        return result

    def _last_whea_check_dt(self) -> Optional[datetime]:
        """Parse the persisted last WHEA poll timestamp (None if unset/invalid)"""
        raw = self.state.last_whea_check
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    
    def _run_final_validation(self) -> None:
        """Run final validation with the converged/derived grid.

        Two phases across a reboot: stage the grid here, then actually test
        it after the next boot (_complete_final_validation) — a final config
        that was never measured is not validation. The last cell search may
        have left an unstable probe value staged, so every cell is re-written.
        """
        logger.info("Running final validation with the converged configuration...")

        # Apply converged grid
        logger.info("Applying converged configuration:")
        for row_idx, row in enumerate(self.state.current_grid):
            logger.info(f"  {ROW_NAMES[row_idx]}: {[f'{v:+d}' for v in row]}")

        cs_set_grid(self.state.current_grid, force=True)
        # Keep best_grid as the historical best-frequency snapshot for the report
        # current_phase (not status) marks the pending validation: status is
        # overwritten to waiting_reboot by the reboot machinery
        self.state.current_phase = "final_validation"
        self.state.save()

        self._reboot_exit("Converged configuration staged for final validation")

    def _complete_final_validation(self) -> None:
        """Final validation phase B: the staged grid is live — measure it"""
        self.state.status = "testing"
        self.state.save()
        logger.info("=== Final Validation: testing the live configuration ===")
        result = self._test_current_configuration()

        logger.info(f"Final validation result: Max Freq = {result.get('max_frequency', 0):.0f} MHz, "
                    f"Stable = {result.get('stable')}, "
                    f"WHEA = {result.get('whea_errors', 'n/a')}")
        if not result.get('stable'):
            logger.warning("Final configuration is NOT stable under stress — "
                           "consider a larger CALIB_MARGIN or a refinement run")

        self.state.status = "completed"
        self.state.current_phase = "completed"
        self.state.save()

    
    def _generate_final_report(self) -> Dict[str, Any]:
        """Generate final optimization report"""
        logger.info("\n" + "="*60)
        logger.info("OPTIMIZATION REPORT")
        logger.info("="*60)
        
        report = {
            'status': self.state.status,
            'mode': self.state.mode,
            'total_iterations': self.state.iteration,
            'total_reboots': self.state.total_reboots,
            'sweeps_completed': self.state.sweep,
            'converged': self.state.converged,
            'cells_optimized': len(self.state.cells_optimized),
            'best_frequency': self.state.best_frequency,
            'best_iteration': self.state.best_iteration,
            'best_grid': self.state.best_grid,
            'calibration_levels_done': list(self.state.calib_offsets_done),
            'attribution_map': dict(self.state.attributed_map) if self.state.attributed_map else None,
            'derived_grid': self.state.derived_grid,
            'derive_report': self.state.derive_report,
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"Status: {self.state.status}")
        logger.info(f"Total Iterations: {self.state.iteration}")
        logger.info(f"Total Reboots: {self.state.total_reboots}")
        logger.info(f"Cells Optimized: {len(self.state.cells_optimized)} / {CS_ROWS * CS_COLS}")
        logger.info(f"Best Frequency: {self.state.best_frequency:.0f} MHz")
        logger.info(f"Best Configuration (Iteration {self.state.best_iteration}):")
        
        for row_idx, row in enumerate(self.state.best_grid):
            logger.info(f"  {ROW_NAMES[row_idx]:5s}: {' '.join([f'{v:+3d}' for v in row])}")
        
        logger.info("="*60)
        
        return report
