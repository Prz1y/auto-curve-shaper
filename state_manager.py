"""
State management for reboot persistence
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, asdict

from config import STATE_FILE, CS_ROWS, CS_COLS

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
    best_stable_offset: int = 0  # Best stable offset found during search
    
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
    
    def __post_init__(self):
        if self.current_grid is None:
            self.current_grid = [[0] * CS_COLS for _ in range(CS_ROWS)]
        if self.best_grid is None:
            self.best_grid = [[0] * CS_COLS for _ in range(CS_ROWS)]
        if self.cells_optimized is None:
            self.cells_optimized = []
        if self.test_results is None:
            self.test_results = []
        if not self.last_update:
            self.last_update = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OptimizationState':
        """Create from dictionary"""
        # Convert cells_optimized from list of lists to list of tuples
        if 'cells_optimized' in data and data['cells_optimized']:
            data['cells_optimized'] = [tuple(cell) if isinstance(cell, list) else cell 
                                      for cell in data['cells_optimized']]
        
        # Convert current_cell
        if 'current_cell' in data and isinstance(data['current_cell'], list):
            data['current_cell'] = tuple(data['current_cell'])
        
        return cls(**data)
    
    def save(self, file_path: Path = STATE_FILE) -> None:
        """Save state to file"""
        self.last_update = datetime.now().isoformat()
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        
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
            logger.error(f"Failed to load state: {e}")
            return None
    
    def mark_cell_optimized(self, row: int, col: int, final_offset: int) -> None:
        """Mark a cell as optimized"""
        cell = (row, col)
        if cell not in self.cells_optimized:
            self.cells_optimized.append(cell)
        
        self.current_grid[row][col] = final_offset
        logger.info(f"Cell ({row}, {col}) optimized with offset {final_offset:+d}")
    
    def get_next_cell_to_optimize(self) -> Optional[tuple]:
        """Get next cell to optimize based on strategy"""
        # Optimization order for maximum frequency:
        # 1. Min row (low temp, affects idle/light load boost)
        # 2. Max row (high temp, affects sustained load)
        # 3. High row (medium-high temp)
        # 4. Low row (low-medium temp)
        # 5. Mid row (medium temp)
        
        optimization_order = [
            # Min row (0) - all temps
            (0, 0), (0, 1), (0, 2),
            # Max row (4) - all temps
            (4, 0), (4, 1), (4, 2),
            # High row (3)
            (3, 0), (3, 1), (3, 2),
            # Low row (1)
            (1, 0), (1, 1), (1, 2),
            # Mid row (2)
            (2, 0), (2, 1), (2, 2),
        ]
        
        for cell in optimization_order:
            if cell not in self.cells_optimized:
                return cell
        
        return None  # All cells optimized
    
    def record_test_result(self, result: Dict[str, Any]) -> None:
        """Record a test result"""
        result['iteration'] = self.iteration
        result['timestamp'] = datetime.now().isoformat()
        self.test_results.append(result)
        
        # Update best if this is better
        if 'max_frequency' in result:
            if result['max_frequency'] > self.best_frequency:
                self.best_frequency = result['max_frequency']
                self.best_grid = [row[:] for row in self.current_grid]  # Deep copy
                self.best_iteration = self.iteration
                logger.info(f"New best frequency: {self.best_frequency:.0f} MHz at iteration {self.iteration}")
    
    def is_completed(self) -> bool:
        """Check if optimization is completed"""
        return len(self.cells_optimized) == CS_ROWS * CS_COLS or self.status == "completed"
    
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
    
    def prepare_for_reboot(self, next_status: str = "testing") -> None:
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
            logger.info("Optimization completed - all cells optimized")
            return False
        
        if self.state.total_reboots >= max_reboots:
            logger.warning(f"Maximum reboots ({max_reboots}) reached")
            return False
        
        if self.state.status == "failed":
            logger.error("Optimization failed")
            return False
        
        return True
