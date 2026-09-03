"""
GUI for Auto Curve Shaper
Modern interface with real-time progress display
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import queue
import sys
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from config import ROW_NAMES, COL_NAMES, CS_ROWS, CS_COLS, VERSION
from optimizer import Optimizer
from state_manager import OptimizationState
from utils import check_admin_privileges


class TextHandler(logging.Handler):
    """Custom logging handler that writes to a text widget"""
    
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.queue = queue.Queue()
        
    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)


class CurveGridWidget(tk.Frame):
    """Widget to display the 5x3 CurveShaper grid"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.cells = {}
        self._create_grid()
    
    def _create_grid(self):
        """Create the grid display"""
        # Header row (temperature columns)
        tk.Label(self, text="", width=8).grid(row=0, column=0, padx=2, pady=2)
        for col_idx, col_name in enumerate(COL_NAMES):
            tk.Label(self, text=col_name, font=("Arial", 10, "bold"), width=10).grid(
                row=0, column=col_idx + 1, padx=2, pady=2
            )
        
        # Grid cells
        for row_idx, row_name in enumerate(ROW_NAMES):
            # Row header
            tk.Label(self, text=row_name, font=("Arial", 10, "bold"), width=8).grid(
                row=row_idx + 1, column=0, padx=2, pady=2
            )
            
            # Cells
            for col_idx in range(CS_COLS):
                cell_frame = tk.Frame(self, relief=tk.RAISED, borderwidth=2, bg="white")
                cell_frame.grid(row=row_idx + 1, column=col_idx + 1, padx=2, pady=2, sticky="nsew")
                
                value_label = tk.Label(cell_frame, text="0", font=("Arial", 12), bg="white")
                value_label.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)
                
                self.cells[(row_idx, col_idx)] = {
                    'frame': cell_frame,
                    'label': value_label
                }
    
    def update_grid(self, grid, current_cell=None, optimized_cells=None):
        """Update grid display"""
        if optimized_cells is None:
            optimized_cells = []
        
        for row_idx in range(CS_ROWS):
            for col_idx in range(CS_COLS):
                cell = self.cells[(row_idx, col_idx)]
                value = grid[row_idx][col_idx]
                
                # Update value
                cell['label'].config(text=f"{value:+d}")
                
                # Update color based on state
                if current_cell == (row_idx, col_idx):
                    # Currently optimizing
                    cell['frame'].config(bg="#FFF3CD")  # Yellow
                    cell['label'].config(bg="#FFF3CD")
                elif (row_idx, col_idx) in optimized_cells:
                    # Optimized
                    cell['frame'].config(bg="#D4EDDA")  # Green
                    cell['label'].config(bg="#D4EDDA")
                elif value != 0:
                    # Modified but not optimized
                    cell['frame'].config(bg="#E7F3FF")  # Light blue
                    cell['label'].config(bg="#E7F3FF")
                else:
                    # Default
                    cell['frame'].config(bg="white")
                    cell['label'].config(bg="white")


class AutoCurveShaperGUI:
    """Main GUI application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"Auto Curve Shaper v{VERSION} - AMD Zen 5 Optimizer")
        self.root.geometry("1000x800")
        
        # State
        self.optimizer: Optional[Optimizer] = None
        self.optimizer_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.state: Optional[OptimizationState] = None
        
        # Setup UI
        self._setup_ui()
        
        # Setup logging
        self._setup_logging()
        
        # Load existing state
        self._load_state()
        
        # Start update loop
        self.root.after(100, self._update_loop)
    
    def _setup_ui(self):
        """Setup the user interface"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Title
        title_label = tk.Label(
            main_frame,
            text=f"Auto Curve Shaper v{VERSION} - AMD Zen 5 Optimizer",
            font=("Arial", 16, "bold")
        )
        title_label.grid(row=0, column=0, pady=(0, 10), sticky=tk.W)
        
        # Status section
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding="10")
        status_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        status_frame.columnconfigure(1, weight=1)
        
        # Status labels
        self.status_label = tk.Label(status_frame, text="Not Started", font=("Arial", 10, "bold"), fg="gray")
        self.status_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        tk.Label(status_frame, text="Iteration:").grid(row=1, column=0, sticky=tk.W)
        self.iteration_label = tk.Label(status_frame, text="0")
        self.iteration_label.grid(row=1, column=1, sticky=tk.W)
        
        tk.Label(status_frame, text="Reboots:").grid(row=2, column=0, sticky=tk.W)
        self.reboots_label = tk.Label(status_frame, text="0")
        self.reboots_label.grid(row=2, column=1, sticky=tk.W)
        
        tk.Label(status_frame, text="Cells Optimized:").grid(row=3, column=0, sticky=tk.W)
        self.cells_label = tk.Label(status_frame, text="0 / 15")
        self.cells_label.grid(row=3, column=1, sticky=tk.W)
        
        tk.Label(status_frame, text="Best Frequency:").grid(row=4, column=0, sticky=tk.W)
        self.freq_label = tk.Label(status_frame, text="0 MHz", font=("Arial", 10, "bold"))
        self.freq_label.grid(row=4, column=1, sticky=tk.W)
        
        # Progress bar
        self.progress_bar = ttk.Progressbar(status_frame, mode='determinate', maximum=15)
        self.progress_bar.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        
        # Grid display
        grid_frame = ttk.LabelFrame(main_frame, text="CurveShaper Grid", padding="10")
        grid_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        
        self.grid_widget = CurveGridWidget(grid_frame)
        self.grid_widget.pack(expand=True)
        
        # Log display
        log_frame = ttk.LabelFrame(main_frame, text="Log", padding="10")
        log_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, sticky=(tk.W, tk.E))
        
        self.start_button = ttk.Button(button_frame, text="Start Optimization", command=self._start_optimization)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_button = ttk.Button(button_frame, text="Stop", command=self._stop_optimization, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.reset_button = ttk.Button(button_frame, text="Reset State", command=self._reset_state)
        self.reset_button.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(button_frame, text="Exit", command=self._exit_app).pack(side=tk.RIGHT)
    
    def _setup_logging(self):
        """Setup logging to GUI"""
        self.log_handler = TextHandler(self.log_text)
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        
        # Add handler to root logger
        logging.getLogger().addHandler(self.log_handler)
    
    def _load_state(self):
        """Load existing state"""
        self.state = OptimizationState.load()
        if self.state:
            self._update_display()
            self._log(f"Loaded existing state: Iteration {self.state.iteration}, Status: {self.state.status}")
        else:
            self._log("No existing state found")
    
    def _update_display(self):
        """Update all display elements"""
        if not self.state:
            return
        
        # Status
        status_text = self.state.status.replace('_', ' ').title()
        self.status_label.config(text=status_text)
        
        if self.state.status == "running":
            self.status_label.config(fg="green")
        elif self.state.status == "completed":
            self.status_label.config(fg="blue")
        elif self.state.status == "failed":
            self.status_label.config(fg="red")
        else:
            self.status_label.config(fg="gray")
        
        # Metrics
        self.iteration_label.config(text=str(self.state.iteration))
        self.reboots_label.config(text=str(self.state.total_reboots))
        self.cells_label.config(text=f"{len(self.state.cells_optimized)} / 15")
        self.freq_label.config(text=f"{self.state.best_frequency:.0f} MHz")
        
        # Progress bar
        self.progress_bar['value'] = len(self.state.cells_optimized)
        
        # Grid
        self.grid_widget.update_grid(
            self.state.current_grid,
            self.state.current_cell,
            self.state.cells_optimized
        )
    
    def _log(self, message):
        """Add log message"""
        self.log_text.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {message}\n")
        self.log_text.see(tk.END)
    
    def _update_loop(self):
        """Update loop to process log messages"""
        # Process log queue
        try:
            while True:
                msg = self.log_handler.queue.get_nowait()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass
        
        # Update display if state changed
        if self.state:
            self._update_display()
        
        # Schedule next update
        self.root.after(100, self._update_loop)
    
    def _start_optimization(self):
        """Start optimization in background thread"""
        # Check admin privileges
        if not check_admin_privileges():
            messagebox.showerror(
                "Administrator Required",
                "This tool requires Administrator privileges!\n\nPlease run as Administrator."
            )
            return
        
        # Confirm
        if self.state and self.state.iteration > 0:
            response = messagebox.askyesno(
                "Continue Optimization",
                f"Found existing state (Iteration {self.state.iteration}).\n\n"
                "Continue from where we left off?"
            )
            if not response:
                return
        else:
            response = messagebox.askyesno(
                "Start Optimization",
                "This will optimize the CurveShaper voltage curve.\n\n"
                "WARNING:\n"
                "- Multiple reboots required (50-100+)\n"
                "- May take hours to days\n"
                "- System may crash if unstable\n\n"
                "Continue?"
            )
            if not response:
                return
        
        # Start optimizer thread
        self.is_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
        self.optimizer_thread = threading.Thread(target=self._run_optimizer, daemon=True)
        self.optimizer_thread.start()
        
        self._log("Starting optimization...")
    
    def _run_optimizer(self):
        """Run optimizer in background thread"""
        try:
            self.optimizer = Optimizer()
            results = self.optimizer.run()
            
            # Update state reference
            self.state = self.optimizer.state
            
            self.root.after(0, lambda: messagebox.showinfo(
                "Optimization Complete",
                f"Optimization finished!\n\n"
                f"Best Frequency: {results['best_frequency']:.0f} MHz\n"
                f"Total Iterations: {results['total_iterations']}\n"
                f"Total Reboots: {results['total_reboots']}"
            ))
            
        except SystemExit as e:
            # Normal exit for reboot
            self._log(str(e))
            self.root.after(0, lambda: messagebox.showinfo(
                "Reboot Required",
                str(e)
            ))
        
        except Exception as e:
            self._log(f"Error: {e}")
            self.root.after(0, lambda: messagebox.showerror(
                "Optimization Error",
                f"An error occurred:\n\n{e}"
            ))
        
        finally:
            self.is_running = False
            self.root.after(0, self._optimization_stopped)
    
    def _optimization_stopped(self):
        """Called when optimization stops"""
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
    
    def _stop_optimization(self):
        """Stop optimization"""
        if self.is_running:
            response = messagebox.askyesno(
                "Stop Optimization",
                "Are you sure you want to stop?\n\n"
                "Progress will be saved and you can resume later."
            )
            if response:
                # Can't really stop thread cleanly, just mark as not running
                self.is_running = False
                self._log("Stopping optimization...")
    
    def _reset_state(self):
        """Reset optimization state"""
        if self.is_running:
            messagebox.showwarning("Cannot Reset", "Stop optimization first")
            return
        
        response = messagebox.askyesno(
            "Reset State",
            "This will delete all optimization progress.\n\n"
            "Are you sure?"
        )
        
        if response:
            if self.state:
                self.state.reset()
                self.state.save()
                self._log("State reset")
                self._update_display()
            else:
                self._log("No state to reset")
    
    def _exit_app(self):
        """Exit application"""
        if self.is_running:
            response = messagebox.askyesno(
                "Exit",
                "Optimization is running. Exit anyway?\n\n"
                "Progress will be saved."
            )
            if not response:
                return
        
        self.root.quit()


def main():
    """Main entry point for GUI"""
    root = tk.Tk()
    app = AutoCurveShaperGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
