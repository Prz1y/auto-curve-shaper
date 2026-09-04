# SPDX-License-Identifier: GPL-3.0-or-later
"""
GUI for Auto Curve Shaper
Modern interface with real-time progress display
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import argparse
import msvcrt
import os
import threading
import queue
import sys
import time
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from config import (
    ROW_NAMES, COL_NAMES, CS_ROWS, CS_COLS, VERSION, MAX_SWEEPS,
    AUTO_CONTINUE_DELAY, AUTO_REBOOT, AUTO_REBOOT_DELAY,
    CALIB_OFFSETS, CALIB_REGIMES, ATTRIB_PROBE_ROWS,
    CALIB_MARGIN, MAX_TEMP_LIMIT, MAX_FREQ_LIMIT, MAX_VOLTAGE_OFFSET,
)
from optimizer import Optimizer
from state_manager import OptimizationState
from frequency_monitor import stop_all_workloads
from utils import (
    check_admin_privileges,
    register_autostart_task, unregister_autostart_task,
    trigger_reboot,
)


class TextHandler(logging.Handler):
    """Custom logging handler that writes to a text widget"""

    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.queue = queue.Queue()

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)


# ---------------------------------------------------------------------------
# Single-instance lock: the autostart task can fire while the user still has
# the GUI open from before the reboot; a second instance would fight over
# state.json and csprobe
#
# MUST be a kernel byte-range lock (msvcrt.locking), NOT a PID written to a
# file: Windows reuses PIDs after a reboot, so "recorded PID is alive" gives
# false positives and the relaunched GUI would refuse to start — stalling the
# unattended loop. Kernel locks are released by the OS when the holder dies,
# so crashes and hard kills can never leave a stale lock.
# ---------------------------------------------------------------------------

LOCK_FILE = Path(__file__).parent / "gui.lock"


def acquire_single_instance_lock():
    """Hold gui.lock for this process; None if a live instance already does.

    Returns the open file handle — it must stay open for the process
    lifetime (closing it releases the lock).
    """
    LOCK_FILE.parent.mkdir(exist_ok=True)
    # O_RDWR|O_CREAT without O_TRUNC: the second opener must not truncate
    # (or destroy) the file the first instance holds the lock on
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o666)
    fh = os.fdopen(fd, 'w+')
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def release_single_instance_lock(fh) -> None:
    """Release the single-instance lock (idempotent)"""
    if fh is None:
        return
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except (OSError, ValueError):
        pass  # already released or handle closed
    try:
        fh.close()
    except OSError:
        pass
    # Leave the file itself in place; ownership is decided by the lock, not
    # the file's existence (and deleting it would race a new acquirer)


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
    
    def __init__(self, root, auto_continue: bool = False, lock=None):
        self._lock = lock
        self.root = root
        self.root.title(f"Auto Curve Shaper v{VERSION} - AMD Zen 5 Optimizer")
        self.root.geometry("1000x800")
        self.auto_continue_requested = auto_continue

        # State
        self.optimizer: Optional[Optimizer] = None
        self.optimizer_thread: Optional[threading.Thread] = None
        self.is_running = False
        self.state: Optional[OptimizationState] = None

        # UI task queue: worker threads never touch tkinter directly
        # (tkinter is not thread-safe)
        self.ui_queue = queue.Queue()

        # Countdown deadlines (epoch seconds); rendered by _update_display
        self._continue_deadline: Optional[float] = None  # auto-continue at logon
        self._reboot_deadline: Optional[float] = None    # auto-reboot after a test iteration
        
        # Setup UI
        self._setup_ui()
        
        # Setup logging
        self._setup_logging()
        
        # Load existing state
        self._load_state()

        # Start update loop
        self.root.after(100, self._update_loop)

        # --continue (autostart task): if a run spans reboots, resume it
        # after a countdown; closing the window aborts
        if self.auto_continue_requested:
            self.root.after(500, self._maybe_schedule_auto_continue)
    
    def _setup_ui(self):
        """Setup the user interface"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
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

        tk.Label(status_frame, text="Sweep:").grid(row=5, column=0, sticky=tk.W)
        self.sweep_label = tk.Label(status_frame, text=f"1 / {MAX_SWEEPS}")
        self.sweep_label.grid(row=5, column=1, sticky=tk.W)

        # Progress bar
        self.progress_bar = ttk.Progressbar(status_frame, mode='determinate', maximum=15)
        self.progress_bar.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

        # Pipeline selection & caps (v1.5 model-first flow)
        pipe_frame = ttk.LabelFrame(main_frame, text="Pipeline & Limits", padding="10")
        pipe_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Label(pipe_frame, text="Mode:").grid(row=0, column=0, sticky=tk.W)
        self.mode_var = tk.StringVar(value="calibrate")
        mode_box = ttk.Combobox(pipe_frame, textvariable=self.mode_var, state="readonly",
                                width=26, values=[
                                    "calibrate",                # sweep -> derive -> verify
                                    "attribute + calibrate",    # differential experiment first
                                    "classic search",           # v1.4 per-cell binary search
                                    "refine current grid",      # residual pass over live grid
                                ])
        mode_box.grid(row=0, column=1, sticky=tk.W, padx=(0, 20))

        ttk.Label(pipe_frame, text="Max Temp (°C):").grid(row=0, column=2, sticky=tk.W)
        self.max_temp_entry = ttk.Entry(pipe_frame, width=7)
        self.max_temp_entry.insert(0, str(MAX_TEMP_LIMIT))
        self.max_temp_entry.grid(row=0, column=3, sticky=tk.W, padx=(0, 15))

        ttk.Label(pipe_frame, text="Max Freq (MHz, 0=off):").grid(row=0, column=4, sticky=tk.W)
        self.max_freq_entry = ttk.Entry(pipe_frame, width=8)
        self.max_freq_entry.insert(0, str(MAX_FREQ_LIMIT))
        self.max_freq_entry.grid(row=0, column=5, sticky=tk.W, padx=(0, 15))

        ttk.Label(pipe_frame, text="Max Offset (+V cap):").grid(row=0, column=6, sticky=tk.W)
        self.max_voltage_entry = ttk.Entry(pipe_frame, width=5)
        self.max_voltage_entry.insert(0, str(MAX_VOLTAGE_OFFSET))
        self.max_voltage_entry.grid(row=0, column=7, sticky=tk.W, padx=(0, 15))

        ttk.Label(pipe_frame, text="Safety Margin:").grid(row=0, column=8, sticky=tk.W)
        self.margin_entry = ttk.Entry(pipe_frame, width=5)
        self.margin_entry.insert(0, str(CALIB_MARGIN))
        self.margin_entry.grid(row=0, column=9, sticky=tk.W)

        self.pipeline_label = tk.Label(pipe_frame, text="pipeline: not started", fg="gray")
        self.pipeline_label.grid(row=1, column=0, columnspan=10, sticky=tk.W, pady=(6, 0))

        # Grid display
        grid_frame = ttk.LabelFrame(main_frame, text="CurveShaper Grid", padding="10")
        grid_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))

        self.grid_widget = CurveGridWidget(grid_frame)
        self.grid_widget.pack(expand=True)

        # Log display
        log_frame = ttk.LabelFrame(main_frame, text="Log", padding="10")
        log_frame.grid(row=4, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Control buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, sticky=(tk.W, tk.E))
        
        self.start_button = ttk.Button(button_frame, text="Start Optimization", command=self._start_optimization)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_button = ttk.Button(button_frame, text="Stop", command=self._stop_optimization, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 5))

        # Visible only during an auto-reboot countdown
        self.reboot_cancel_btn = ttk.Button(button_frame, text="Cancel Reboot", command=self._cancel_pending_reboot)
        self.reboot_cancel_btn.pack(side=tk.LEFT, padx=(0, 5))
        self.reboot_cancel_btn.pack_forget()
        
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

        # Countdowns take precedence over the persisted status: they expire
        # every second and would otherwise be overwritten by this method
        now = time.time()
        if self._reboot_deadline is not None:
            remaining = max(0, int(self._reboot_deadline - now))
            self.status_label.config(
                text=f"Auto-reboot in {remaining}s... (Cancel Reboot to stay up)",
                fg="orange")
        elif self._continue_deadline is not None:
            remaining = max(0, int(self._continue_deadline - now))
            self.status_label.config(
                text=f"Auto-continue in {remaining}s... (close window to abort)",
                fg="orange")
        else:
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
        self.sweep_label.config(text=f"{self.state.sweep} / {MAX_SWEEPS}")

        # Pipeline progress line + bar scale follow the active phase
        if self.state.mode in ("attribute", "calibrate"):
            done = len(self.state.calib_offsets_done)
            if self.state.mode == "attribute":
                txt = (f"Attribution: {len(self.state.attrib_rows_done)}/"
                       f"{len(ATTRIB_PROBE_ROWS)} probe rows done")
                if done:
                    txt += f" | calibration {done}/{len(CALIB_OFFSETS)} levels"
            else:
                txt = f"Calibration: {done}/{len(CALIB_OFFSETS)} offset levels"
            if self.state.calib_current_offset is not None and self.state.calib_regime_index:
                txt += (f" | level {self.state.calib_current_offset:+d}, "
                        f"window {self.state.calib_regime_index}/{len(CALIB_REGIMES)}")
            self.pipeline_label.config(text=txt, fg="black")
            self.progress_bar.configure(maximum=len(CALIB_OFFSETS), value=done)
        elif self.state.derive_report:
            peak = self.state.derive_report.get('peak_freq_pred_mhz', 0)
            warn = self.state.derive_report.get('warnings') or []
            txt = f"Derived grid (peak predicted {peak} MHz) — {'%d warning(s), ' % len(warn) if warn else ''}verify pass"
            self.pipeline_label.config(text=txt, fg="black")
            self.progress_bar.configure(maximum=15, value=len(self.state.cells_optimized))
        else:
            self.pipeline_label.config(text="pipeline: not started", fg="gray")
            self.progress_bar.configure(maximum=15, value=len(self.state.cells_optimized))

        # Grid
        self.grid_widget.update_grid(
            self.state.current_grid,
            self.state.current_cell,
            self.state.cells_optimized
        )
    
    def _post_to_ui(self, task):
        """Queue a callable to run on the main Tk thread"""
        self.ui_queue.put(task)

    def _log(self, message):
        """Add log message (thread-safe: routed through the UI queue)"""
        line = f"{datetime.now().strftime('%H:%M:%S')} - {message}\n"
        self._post_to_ui(lambda: self._append_log_line(line))

    def _append_log_line(self, line):
        self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)

    def _update_loop(self):
        """Update loop: run queued UI tasks and process log messages"""
        # Run UI tasks queued by worker threads
        try:
            while True:
                task = self.ui_queue.get_nowait()
                task()
        except queue.Empty:
            pass

        # Process log handler queue
        try:
            while True:
                msg = self.log_handler.queue.get_nowait()
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
        except queue.Empty:
            pass

        # Follow the optimizer's live state object instead of a startup
        # snapshot, so the display keeps updating across reboot cycles
        if self.optimizer is not None and self.optimizer.state is not None:
            self.state = self.optimizer.state

        # Update display if state changed
        if self.state:
            self._update_display()

        # Schedule next update
        self.root.after(100, self._update_loop)
    
    def _maybe_schedule_auto_continue(self):
        """--continue launch (autostart task): auto-resume after a countdown"""
        if not self.state or self.state.status != "waiting_reboot":
            self._log("Auto-continue: no pending run, manual mode")
            return
        self._continue_deadline = time.time() + AUTO_CONTINUE_DELAY
        self._log(f"Auto-continuing optimization in {AUTO_CONTINUE_DELAY}s "
                  f"(close this window to abort)")
        self.root.after(1000, self._continue_tick)

    def _continue_tick(self):
        if self._continue_deadline is None:
            return
        if self.is_running or self._reboot_deadline is not None:
            self._continue_deadline = None
            return
        if time.time() >= self._continue_deadline:
            self._continue_deadline = None
            self._log("Auto-continue: resuming optimization...")
            self._start_optimization(auto=True)
            return
        self.root.after(1000, self._continue_tick)

    # -- auto-reboot -------------------------------------------------------

    def _begin_reboot_countdown(self):
        """Called when the optimizer needs a reboot and AUTO_REBOOT is on"""
        self._reboot_deadline = time.time() + AUTO_REBOOT_DELAY
        self.reboot_cancel_btn.pack()
        self._log(f"Auto-reboot in {AUTO_REBOOT_DELAY}s — "
                  f"click 'Cancel Reboot' to stay up (the run resumes "
                  f"automatically at next logon either way)")
        self.root.after(1000, self._reboot_tick)

    def _reboot_tick(self):
        if self._reboot_deadline is None:
            return
        if time.time() >= self._reboot_deadline:
            self._reboot_deadline = None
            self.reboot_cancel_btn.pack_forget()
            self._log("Rebooting now to apply the new configuration...")
            trigger_reboot(5)
            return
        self.root.after(1000, self._reboot_tick)

    def _cancel_pending_reboot(self):
        """User chose to stay up: the run resumes at next manual reboot+logon"""
        if self._reboot_deadline is None:
            return
        self._reboot_deadline = None
        self.reboot_cancel_btn.pack_forget()
        self._log("Auto-reboot cancelled. Reboot manually whenever ready — "
                  "afterwards the tool auto-continues (or click Start).")

    def _read_caps(self) -> dict:
        """Parse the Limits entries; None (dialog shown) on bad input"""
        try:
            return {
                'max_temp': float(self.max_temp_entry.get().strip() or MAX_TEMP_LIMIT),
                'max_freq': float(self.max_freq_entry.get().strip() or 0),
                'max_voltage': int(self.max_voltage_entry.get().strip() or 0),
                'margin': int(self.margin_entry.get().strip() or CALIB_MARGIN),
            }
        except ValueError as e:
            messagebox.showerror("Invalid Limits", f"Limit fields must be numeric:\n{e}")
            return None

    def _apply_mode_selection(self) -> bool:
        """Apply the pipeline combobox to the persisted state.

        Returns False when the user cancelled. Auto-continue never comes here:
        a resuming run must keep the mode/caps it was started with.
        """
        selected = self.mode_var.get()
        if self.state is None:
            self.state = OptimizationState()

        if selected == "refine current grid":
            if not messagebox.askyesno(
                    "Refine Current Grid",
                    "Re-run the per-cell search over the current grid?\n\n"
                    "Use this to squeeze residuals after a derived grid, or on\n"
                    "an existing configuration. Several dozen reboots."):
                return False
            self.state.seed_full_refinement()
            self.state.save()
            return True

        if selected == "classic search":
            caps = self._read_caps()
            if caps is None:
                return False
            # continuing an in-progress run keeps its mode untouched
            if not (self.state.iteration > 0 or self.state.calib_offsets_done
                    or self.state.attrib_rows_done or self.state.calib_rows):
                self.state.mode = "standard"
            self.state.caps = caps
            self.state.save()
            return True

        pipeline_mode = "calibrate" if selected == "calibrate" else "attribute"
        has_progress = bool(
            self.state.iteration > 0 or self.state.calib_offsets_done
            or self.state.attrib_rows_done or self.state.calib_rows)

        if self.state.mode != pipeline_mode and has_progress:
            if not messagebox.askyesno(
                    "Switch Pipeline",
                    f"Existing progress belongs to mode '{self.state.mode}'.\n\n"
                    f"Starting '{pipeline_mode}' RESETS that progress and begins\n"
                    "a fresh calibration sweep. Continue?"):
                return False
            self.state.reset()

        self.state.mode = pipeline_mode
        caps = self._read_caps()
        if caps is None:
            return False
        self.state.caps = caps
        self.state.save()
        return True

    def _start_optimization(self, auto: bool = False):
        """Start optimization in background thread.

        auto=True comes from the post-logon auto-continue: the run was already
        consented to when it started, so no dialogs may block the unattended
        loop. Manual clicks keep the confirmations.
        """
        self._continue_deadline = None  # a start supersedes a pending auto-continue

        # Check admin privileges
        if not check_admin_privileges():
            if not auto:
                messagebox.showerror(
                    "Administrator Required",
                    "This tool requires Administrator privileges!\n\nPlease run as Administrator."
                )
            else:
                self._log("ERROR: not running as Administrator - cannot continue")
            return

        # Confirm (manual starts only)
        if not auto:
            if not self._apply_mode_selection():
                return
            pipeline = self.state.mode in ("attribute", "calibrate")
            if pipeline:
                probe_note = ("+ 5 attribution reboots first\n"
                              if self.state.mode == "attribute" else "")
                fresh_text = (
                    "This will CALIBRATE the CurveShaper model, derive the\n"
                    "optimal grid, then verify it.\n\n"
                    "WARNING:\n"
                    f"- Reboots: 1 per offset level ({len(CALIB_OFFSETS)} levels), {probe_note}"
                    "  plus validation (~12-20 total, 60s cancelable countdown)\n"
                    "- Each level runs ~10 min of load windows (y-cruncher,\n"
                    "  pinned-core burn, throttled loads)\n"
                    "- Save and close ALL other work before starting\n"
                    "- System may crash if an offset level is unstable\n\n"
                    "Continue?")
            else:
                fresh_text = (
                    "This will optimize the CurveShaper voltage curve.\n\n"
                    "WARNING:\n"
                    "- The system will REBOOT AUTOMATICALLY (~100-200 times,\n"
                    "  60s cancelable countdown before each reboot)\n"
                    "- Save and close ALL other work before starting\n"
                    "- The run can proceed unattended for hours or days\n"
                    "- System may crash if unstable\n\n"
                    "Continue?")
            if self.state and self.state.iteration > 0:
                response = messagebox.askyesno(
                    "Continue Optimization",
                    f"Found existing state (Iteration {self.state.iteration}, "
                    f"mode '{self.state.mode}').\n\n"
                    "Continue from where we left off?"
                )
                if not response:
                    return
            else:
                response = messagebox.askyesno(
                    "Start Optimization", fresh_text
                )
                if not response:
                    return
        
        # Start optimizer thread
        self.is_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)

        # Relaunch ourselves at logon while the run spans reboots
        if not register_autostart_task():
            self._log("WARNING: could not register logon autostart - "
                      "you must relaunch the GUI manually after each reboot")

        self.optimizer_thread = threading.Thread(target=self._run_optimizer, daemon=True)
        self.optimizer_thread.start()

        self._log("Starting optimization...")
    
    def _run_optimizer(self):
        """Run optimizer in background thread"""
        try:
            self.optimizer = Optimizer()
            results = self.optimizer.run()

            # Run finished (completed/failed/max reboots) — the autostart
            # task must not linger and surprise the user at next logon
            unregister_autostart_task()

            summary = (f"Optimization finished!\n\n"
                       f"Best Frequency: {results['best_frequency']:.0f} MHz\n"
                       f"Total Iterations: {results['total_iterations']}\n"
                       f"Total Reboots: {results['total_reboots']}")
            self._post_to_ui(lambda: messagebox.showinfo("Optimization Complete", summary))

        except SystemExit as e:
            # Normal exit: the new configuration is staged, a reboot applies it
            msg = str(e)
            self._log(msg)
            if AUTO_REBOOT:
                self._post_to_ui(self._begin_reboot_countdown)
            else:
                self._post_to_ui(lambda: messagebox.showinfo("Reboot Required", msg))

        except Exception as e:
            self._log(f"Error: {e}")
            msg = f"An error occurred:\n\n{e}"
            self._post_to_ui(lambda: messagebox.showerror("Optimization Error", msg))

        finally:
            self.is_running = False
            self._post_to_ui(self._optimization_stopped)
    
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
                # The optimizer thread cannot be interrupted mid-test, but
                # killing the workload makes the current test fail fast so
                # the run ends at the next reboot prompt
                self.is_running = False
                self._log("Stopping optimization...")
                stop_all_workloads()
                unregister_autostart_task()
                self._cancel_pending_reboot()
                self._log("Workload terminated; optimizer will stop at the next reboot prompt")
    
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
            self._cancel_pending_reboot()
            if self.state:
                self.state.reset()
                self.state.save()
                self._log("State reset")
                self._update_display()
            else:
                self._log("No state to reset")
    
    def _exit_app(self):
        """Exit application"""
        self._continue_deadline = None  # closing the window aborts auto-continue

        if self.is_running:
            response = messagebox.askyesno(
                "Exit",
                "Optimization is running. Exit anyway?\n\n"
                "Progress will be saved."
            )
            if not response:
                return

        # Keep the autostart task while a run spans reboots (exiting here is
        # the normal flow: reboot, task relaunches us) — otherwise remove it
        if not (self.state and self.state.status == "waiting_reboot"):
            unregister_autostart_task()

        # Drop any pending auto-reboot countdown; if the OS shutdown is
        # already scheduled (<5s window), abort it too — an explicit exit
        # means the user wants the machine to stay up
        if self._reboot_deadline is not None:
            self._reboot_deadline = None
            self.reboot_cancel_btn.pack_forget()
            from utils import cancel_reboot
            cancel_reboot()

        # Kill any burn.exe we started, otherwise it keeps the CPU pinned
        # at full load after the GUI is gone
        stop_all_workloads()

        release_single_instance_lock(self._lock)
        self._lock = None
        self._exit_handled = True
        self.root.quit()


def main():
    """Main entry point for GUI"""
    parser = argparse.ArgumentParser(description="Auto Curve Shaper GUI")
    parser.add_argument("--continue", dest="auto_continue", action="store_true",
                        help="auto-resume a reboot-spanning optimization run "
                             "(used by the logon autostart task)")
    args = parser.parse_args()

    lock = acquire_single_instance_lock()
    if lock is None:
        # A live instance owns the run. Do NOT unregister the autostart task
        # here — the running instance depends on it for auto-resume.
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "Already Running",
            "Another Auto Curve Shaper window is already open.\n"
            "Use the existing window."
        )
        return

    app = None
    try:
        root = tk.Tk()
        app = AutoCurveShaperGUI(root, auto_continue=args.auto_continue, lock=lock)
        root.protocol("WM_DELETE_WINDOW", app._exit_app)
        root.mainloop()
    finally:
        # Crash path cleanup: a lingering autostart task would pop the GUI at
        # every logon with no run in progress. _exit_app already handled the
        # normal paths (keeping the task while a run spans reboots), so here
        # we only remove it if the app never got the chance.
        if app is None or not getattr(app, '_exit_handled', False):
            unregister_autostart_task()
        release_single_instance_lock(lock)


if __name__ == "__main__":
    main()
