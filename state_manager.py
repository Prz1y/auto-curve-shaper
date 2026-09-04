# SPDX-License-Identifier: GPL-3.0-or-later
"""
State management for reboot persistence
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, asdict, fields

from config import STATE_FILE, CS_ROWS, CS_COLS

# Number of recent test results kept in state.json (full history goes to logs)
MAX_STORED_RESULTS = 20

logger = logging.getLogger(__name__)


@dataclass
class OptimizationState:
    """State that persists across reboots"""
    
    # Current iteration
    iteration: int = 0
    total_reboots: int = 0
    
    # Current grid being tested
    current_grid: List[List[int]] = None  # 5x3 grid
    
    # Optimization progress
    cells_optimized: List[tuple] = None  # [(row, col), ...] completed cells
    current_cell: Optional[tuple] = None  # (row, col) being optimized
    
    # Binary search state for current cell
    search_min: int = -30
    search_max: int = 0
    search_current: int = 0
    best_stable_offset: int = 0  # Best stable offset found for the CURRENT cell (reset per cell)

    # WHEA polling: ISO timestamp of the last check, so each poll only counts
    # new errors instead of re-counting old ones inside a fixed window
    last_whea_check: str = ""

    # Multi-sweep refinement: shaper fields overlap, so after the first full
    # pass every cell is re-searched (seeded from its previous optimum) until
    # a full sweep changes nothing
    sweep: int = 1  # current sweep number, 1-based
    sweep_remaining: List[tuple] = None  # cells left in the current sweep
    sweep_changes: int = 0  # cells whose optimum changed during the current sweep
    converged: bool = False  # no further sweeps needed
    
    # Best results
    best_grid: List[List[int]] = None
    best_frequency: float = 0.0
    best_iteration: int = 0
    
    # Test results history
    test_results: List[Dict[str, Any]] = None
    
    # Status
    status: str = "not_started"  # not_started, running, waiting_reboot, testing, completed, failed
    last_update: str = ""
    error_message: str = ""
    
    # Phase tracking
    current_phase: str = "baseline"  # baseline, optimize_min, optimize_low, optimize_mid, optimize_high, optimize_max, fine_tune, completed

    # ------------------------------------------------------------------
    # v1.5 model-first pipeline
    # mode "attribute"  — differential attribution experiment (row +30 probe)
    # mode "calibrate"  — uniform-grid offset sweep, full-spectrum battery
    # mode "standard"   — classic search / verify-and-finish loop
    # ------------------------------------------------------------------
    mode: str = "standard"

    # Attribution experiment
    attrib_probe_row: Optional[int] = None   # CS row currently probed with +30
    attrib_rows_done: List[int] = None       # probe rows completed
    attributed_map: Optional[Dict[str, int]] = None  # regime -> row (None = config default)

    # Calibration sweep progress
    calib_current_offset: Optional[int] = None  # offset level currently staged
    calib_offsets_done: List[int] = None        # offset levels with complete battery
    calib_regime_index: int = 0                 # next battery window for current offset
    calib_rows: List[Dict[str, Any]] = None     # all battery rows (the three tables)
    calib_baseline: List[Dict[str, Any]] = None  # offset-0 battery (attribution reference)

    # Caps snapshot in force for the derivation (GUI-editable before start)
    caps: Optional[Dict[str, Any]] = None

    # Derivation output
    derived_grid: Optional[List[List[int]]] = None
    derive_report: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.current_grid is None:
            self.current_grid = [[0] * CS_COLS for _ in range(CS_ROWS)]
        if self.best_grid is None:
            self.best_grid = [[0] * CS_COLS for _ in range(CS_ROWS)]
        if self.cells_optimized is None:
            self.cells_optimized = []
        if self.test_results is None:
            self.test_results = []
        if self.sweep_remaining is None:
            self.sweep_remaining = []
        if self.attrib_rows_done is None:
            self.attrib_rows_done = []
        if self.calib_offsets_done is None:
            self.calib_offsets_done = []
        if self.calib_rows is None:
            self.calib_rows = []
        if self.calib_baseline is None:
            self.calib_baseline = []
        if not self.last_update:
            self.last_update = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OptimizationState':
        """Create from dictionary, ignoring unknown keys for forward compatibility"""
        known_fields = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in known_fields}

        # Convert cells_optimized from list of lists to list of tuples
        if data.get('cells_optimized'):
            data['cells_optimized'] = [tuple(cell) if isinstance(cell, list) else cell
                                       for cell in data['cells_optimized']]

        # Convert current_cell
        if isinstance(data.get('current_cell'), list):
            data['current_cell'] = tuple(data['current_cell'])

        # Convert sweep queue
        if data.get('sweep_remaining'):
            data['sweep_remaining'] = [tuple(cell) if isinstance(cell, list) else cell
                                       for cell in data['sweep_remaining']]

        return cls(**data)
    
    def save(self, file_path: Path = STATE_FILE) -> None:
        """Save state to file.

        Writes to a temp file and atomically replaces the target: this tool
        saves right before the user reboots the machine, so a plain open('w')
        can be killed mid-write by the reboot and corrupt weeks of progress.
        """
        self.last_update = datetime.now().isoformat()

        tmp_path = file_path.with_name(file_path.name + '.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)

        logger.debug(f"State saved to {file_path}")
    
    @classmethod
    def load(cls, file_path: Path = STATE_FILE) -> Optional['OptimizationState']:
        """Load state from file"""
        if not file_path.exists():
            logger.info("No existing state file found")
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            state = cls.from_dict(data)
            logger.info(f"State loaded from {file_path} - Iteration {state.iteration}, Status: {state.status}")
            return state
            
        except Exception as e:
            # Back up the unusable file so weeks of reboot progress is never
            # silently destroyed, then start fresh
            backup = file_path.with_name(
                f"{file_path.stem}.corrupt_{datetime.now().strftime('%Y%m%d_%H%M%S')}{file_path.suffix}"
            )
            try:
                os.replace(file_path, backup)
                logger.error(f"Failed to load state ({e}); backed up to {backup}")
            except OSError:
                logger.error(f"Failed to load state: {e} (could not back up {file_path})")
            return None
    
    def mark_cell_optimized(self, row: int, col: int, final_offset: int) -> None:
        """Mark a cell as optimized"""
        cell = (row, col)
        if cell not in self.cells_optimized:
            self.cells_optimized.append(cell)
        
        self.current_grid[row][col] = final_offset
        logger.info(f"Cell ({row}, {col}) optimized with offset {final_offset:+d}")
    
    @staticmethod
    def optimization_order() -> List[tuple]:
        """Fixed cell optimization order for maximum frequency:
        Min row (low temp, affects idle/light load boost), Max row (sustained
        load), then High, Low, Mid rows"""
        return [
            (0, 0), (0, 1), (0, 2),
            (4, 0), (4, 1), (4, 2),
            (3, 0), (3, 1), (3, 2),
            (1, 0), (1, 1), (1, 2),
            (2, 0), (2, 1), (2, 2),
        ]

    def get_next_cell_to_optimize(self) -> Optional[tuple]:
        """Pop the next cell from the current sweep's queue"""
        if not self.sweep_remaining:
            return None
        return self.sweep_remaining.pop(0)
    
    def record_test_result(self, result: Dict[str, Any]) -> None:
        """Record a test result.

        Keeps the most recent MAX_STORED_RESULTS entries: the full history
        lives in the session logs, and an unbounded list makes every save()
        rewrite a growing multi-hundred-entry JSON on each of the hundreds of
        reboots.
        """
        result['iteration'] = self.iteration
        result['timestamp'] = datetime.now().isoformat()
        self.test_results.append(result)
        if len(self.test_results) > MAX_STORED_RESULTS:
            self.test_results = self.test_results[-MAX_STORED_RESULTS:]
        
        # Update best if this is better
        if 'max_frequency' in result:
            if result['max_frequency'] > self.best_frequency:
                self.best_frequency = result['max_frequency']
                self.best_grid = [row[:] for row in self.current_grid]  # Deep copy
                self.best_iteration = self.iteration
                logger.info(f"New best frequency: {self.best_frequency:.0f} MHz at iteration {self.iteration}")
    
    def is_completed(self) -> bool:
        """Check if optimization is completed"""
        return self.status == "completed" or self.converged

    def seed_verify_from_grid(self, grid: List[List[int]]) -> None:
        """Enter the standard loop in verify-only mode over a derived grid.

        Empty sweep queue + sweep>=2 + zero sweep_changes makes the existing
        flow go straight to convergence and final validation: one full test of
        the derived grid, no per-cell re-search. Residual refinement stays
        available via seed_full_refinement().
        """
        self.mode = "standard"
        self.current_grid = [row[:] for row in grid]
        self.best_grid = [row[:] for row in grid]
        self.cells_optimized = [(r, c) for r in range(CS_ROWS) for c in range(CS_COLS)]
        self.sweep = 2
        self.sweep_remaining = []
        self.sweep_changes = 0
        self.converged = False

    def seed_full_refinement(self) -> None:
        """Re-run the per-cell search over the current grid (residual engine).

        Seeded from current values (sweep>=2 path), one full pass, converging
        immediately if nothing moves.
        """
        self.mode = "standard"
        self.cells_optimized = [(r, c) for r in range(CS_ROWS) for c in range(CS_COLS)]
        self.sweep = 2
        self.sweep_changes = 0
        self.converged = False
        self.sweep_remaining = list(self.optimization_order())
    
    def reset(self) -> None:
        """Reset state for new optimization run"""
        self.__init__()
        self.status = "not_started"
        self.last_update = datetime.now().isoformat()


class RebootManager:
    """Manages reboot cycle and state persistence"""
    
    def __init__(self):
        self.state: Optional[OptimizationState] = None
    
    def initialize(self) -> OptimizationState:
        """Initialize or restore state"""
        self.state = OptimizationState.load()
        
        if self.state is None:
            logger.info("Initializing new optimization state")
            self.state = OptimizationState()
        else:
            logger.info(f"Restored state: iteration {self.state.iteration}, "
                       f"status {self.state.status}, reboots {self.state.total_reboots}")
        
        return self.state
    
    def prepare_for_reboot(self) -> None:
        """Prepare state before reboot"""
        if self.state is None:
            raise RuntimeError("State not initialized")

        self.state.status = "waiting_reboot"
        self.state.total_reboots += 1
        self.state.save()

        logger.info(f"State saved before reboot #{self.state.total_reboots}")
    
    def after_reboot(self) -> None:
        """Update state after reboot"""
        if self.state is None:
            raise RuntimeError("State not initialized")
        
        self.state.status = "testing"
        self.state.save()
        
        logger.info("State updated after reboot")
    
    def is_waiting_for_reboot(self) -> bool:
        """Check if we're waiting for a reboot"""
        return self.state and self.state.status == "waiting_reboot"
    
    def should_continue(self, max_reboots: int) -> bool:
        """Check if optimization should continue"""
        if self.state is None:
            return True

        if self.state.is_completed():
            if self.state.current_phase == "final_validation":
                pass  # converged, but the final validation test is still pending
            else:
                logger.info("Optimization completed - all cells optimized")
                return False
        
        if self.state.total_reboots >= max_reboots:
            logger.warning(f"Maximum reboots ({max_reboots}) reached")
            return False
        
        if self.state.status == "failed":
            logger.error("Optimization failed")
            return False
        
        return True
