"""
Core optimization engine
"""
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime

from config import (
    INITIAL_OFFSET, MIN_SAFE_OFFSET, STEP_SIZE,
    IDLE_SAMPLE_DURATION, LOAD_SAMPLE_DURATION,
    STABILITY_TEST_DURATION, CS_ROWS, CS_COLS,
    ROW_NAMES, COL_NAMES, MAX_REBOOT_ATTEMPTS
)
from state_manager import OptimizationState, RebootManager
from frequency_monitor import (
    measure_frequencies_idle,
    measure_frequencies_load,
    run_stability_test,
    check_whea_errors
)
from utils import cs_set_grid, cs_clear, cs_set_cell

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
        
        # Check if we just rebooted
        if self.state.status == "waiting_reboot":
            logger.info("Detected post-reboot state, continuing optimization...")
            self.reboot_mgr.after_reboot()
            time.sleep(5)  # Brief delay after boot
        
        # Check if we should continue
        if not self.reboot_mgr.should_continue(MAX_REBOOT_ATTEMPTS):
            return self._generate_final_report()
        
        # Main optimization loop
        try:
            if self.state.iteration == 0:
                # First run: establish baseline
                logger.info("=== Starting Optimization: Baseline Measurement ===")
                self._run_baseline()
            
            # Optimize each cell
            while not self.state.is_completed():
                if not self.reboot_mgr.should_continue(MAX_REBOOT_ATTEMPTS):
                    break
                
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
        logger.info("Baseline configuration set. Need to reboot for changes to take effect.")
        logger.info("Please reboot and run the optimizer again.")
        
        self.reboot_mgr.prepare_for_reboot(next_status="testing")
        
        # In a real implementation, would trigger automatic reboot
        # For now, exit and wait for manual reboot
        raise SystemExit("Please reboot the system and run the optimizer again.")
    
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
                self.state.mark_cell_optimized(row, col, optimal_offset)
                self.state.current_cell = None
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
    
    def _start_binary_search(self, row: int, col: int) -> None:
        """
        Start binary search for optimal offset for a single cell
        """
        # Initialize search range
        self.state.search_min = MIN_SAFE_OFFSET  # -30
        self.state.search_max = 0  # No positive voltage for max frequency strategy
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
        
        raise SystemExit("Please reboot and run the optimizer again.")
    
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
        
        # Track best stable offset
        if not hasattr(self.state, 'best_stable_offset'):
            self.state.best_stable_offset = 0
        
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
        
        raise SystemExit("Please reboot and run the optimizer again.")
    
    def _binary_search_cell(self, row: int, col: int) -> int:
        """
        Binary search for optimal offset for a single cell (legacy method)
        This is now split into _start_binary_search and _continue_binary_search
        """
        raise NotImplementedError("Use _start_binary_search and _continue_binary_search instead")
    
    def _test_current_configuration(self) -> Dict[str, Any]:
        """
        Test current configuration and return results
        """
        logger.info("Testing current configuration...")
        
        result = {
            'grid': [row[:] for row in self.state.current_grid],
            'timestamp': datetime.now().isoformat()
        }
        
        # Check for WHEA errors from boot
        whea_count = check_whea_errors()
        result['whea_errors'] = whea_count
        
        if whea_count > 0:
            logger.warning(f"WHEA errors detected: {whea_count} - configuration is unstable")
            result['stable'] = False
            result['idle_freq'] = None
            result['load_freq'] = None
            result['max_frequency'] = 0.0
            return result
        
        # Measure idle frequencies
        try:
            idle_measurement = measure_frequencies_idle(IDLE_SAMPLE_DURATION)
            result['idle_freq'] = {
                'ccd0': idle_measurement.ccd0_freq,
                'ccd1': idle_measurement.ccd1_freq,
                'avg': idle_measurement.avg_frequency,
                'max': idle_measurement.max_frequency,
                'all_cores': idle_measurement.all_cores
            }
        except Exception as e:
            logger.error(f"Idle measurement failed: {e}")
            result['idle_freq'] = None
        
        # Measure load frequencies
        try:
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
            
        except Exception as e:
            logger.error(f"Load measurement failed: {e}")
            result['load_freq'] = None
            result['max_frequency'] = 0.0
        
        # Quick stability test
        try:
            stable = run_stability_test(STABILITY_TEST_DURATION)
            result['stable'] = stable
            
            if not stable:
                logger.warning("Stability test failed")
                result['max_frequency'] = 0.0  # Unstable config gets 0 score
        except Exception as e:
            logger.error(f"Stability test failed: {e}")
            result['stable'] = False
            result['max_frequency'] = 0.0
        
        # Record result
        self.state.record_test_result(result)
        self.state.save()
        
        logger.info(f"Test result: Max Freq = {result['max_frequency']:.0f} MHz, Stable = {result.get('stable', False)}")
        
        return result
    
    def _run_final_validation(self) -> None:
        """Run final validation with best configuration"""
        logger.info("Running final validation with best configuration...")
        
        # Apply best grid
        logger.info("Applying best configuration:")
        for row_idx, row in enumerate(self.state.best_grid):
            logger.info(f"  {ROW_NAMES[row_idx]}: {[f'{v:+d}' for v in row]}")
        
        cs_set_grid(self.state.best_grid, force=True)
        self.state.current_grid = [row[:] for row in self.state.best_grid]
        self.state.save()
        
        # Would trigger reboot here
        logger.info("Best configuration applied. Reboot required for final validation.")
    
    def _generate_final_report(self) -> Dict[str, Any]:
        """Generate final optimization report"""
        logger.info("\n" + "="*60)
        logger.info("OPTIMIZATION REPORT")
        logger.info("="*60)
        
        report = {
            'status': self.state.status,
            'total_iterations': self.state.iteration,
            'total_reboots': self.state.total_reboots,
            'cells_optimized': len(self.state.cells_optimized),
            'best_frequency': self.state.best_frequency,
            'best_iteration': self.state.best_iteration,
            'best_grid': self.state.best_grid,
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
