# Auto Curve Shaper

Automatic AMD Zen 5 CurveShaper voltage curve optimization tool.

**Target Platform:** AMD Ryzen 9000 (Zen 5) Desktop CPUs  
**Optimization Goal:** Maximum CPU Frequency  
**Requirements:** Windows, Administrator privileges

## Overview

This tool automatically explores the CurveShaper voltage curve space to find the optimal settings for maximum CPU frequency. It uses a systematic optimization approach with stability testing and automatic reboot management.

## Features

- ✅ **Fully Automated**: Binary search optimization for each CurveShaper cell
- ✅ **Reboot Persistence**: State management across reboots
- ✅ **Stability Testing**: WHEA error detection and stress testing
- ✅ **Frequency Monitoring**: Real-time idle and load frequency measurement
- ✅ **Safety Mechanisms**: Conservative starting points, validation checks
- ✅ **Progress Tracking**: Detailed logging and status reporting

## Architecture

```
auto-curve-shaper/
├── main.py                  # CLI entry point
├── gui.py                   # GUI application
├── optimizer.py             # Core optimization engine
├── state_manager.py         # Reboot persistence and state tracking
├── frequency_monitor.py     # CPU frequency measurement
├── utils.py                 # Utility functions and csprobe wrapper
├── config.py                # Configuration parameters
├── run.cmd / run.ps1        # CLI launchers
├── run-gui.cmd / run-gui.ps1 # GUI launchers
├── state.json               # Current optimization state (auto-generated)
├── results/                 # Test results (auto-generated)
└── logs/                    # Execution logs (auto-generated)
```

## How It Works

### CurveShaper Grid

The tool optimizes a 5×3 grid of voltage offsets:

| Frequency Point | 0°C | 50°C | 100°C |
|-----------------|-----|------|-------|
| Min             | ±30 | ±30  | ±30   |
| Low             | ±30 | ±30  | ±30   |
| Mid             | ±30 | ±30  | ±30   |
| High            | ±30 | ±30  | ±30   |
| Max             | ±30 | ±30  | ±30   |

### Optimization Strategy

1. **Baseline Measurement**: Measure performance with all offsets at 0
2. **Cell-by-Cell Optimization**: Optimize each cell in priority order:
   - Min row (affects low-temp boost behavior)
   - Max row (affects sustained high-load performance)
   - High, Low, Mid rows
3. **Binary Search**: For each cell, find the most aggressive stable offset
4. **Stability Validation**: Each configuration is tested for:
   - WHEA error absence
   - Stress test stability
   - Frequency measurements under idle and load
5. **Final Validation**: Best configuration is validated with extended testing

### Iteration Cycle

Each optimization iteration:
1. Set new CurveShaper values via `csprobe cs-set`
2. Save state to disk
3. Reboot system (changes only apply after POST)
4. Resume from saved state
5. Run stability and frequency tests
6. Update best configuration if improved
7. Continue to next cell

## Usage

### Prerequisites

1. AMD Ryzen 9000 (Zen 5) CPU
2. Windows with Administrator privileges
3. Python 3.8 or higher
4. cs-probe tools installed at `C:\Users\deepi\.zcode\workspace\default\cs-probe`

### Running the Optimizer

#### Option A: GUI (Recommended)

```bash
# Double-click run-gui.cmd or run-gui.ps1
# Or run:
python gui.py
```

The GUI provides:
- Real-time progress display
- 5×3 CurveShaper grid visualization
- Live log output
- Status monitoring
- Easy start/stop/reset controls

#### Option B: Command Line

```bash
# Double-click run.cmd or run.ps1
# Or run:
python main.py
```

The CLI tool will:
- Check for existing optimization state
- Prompt for confirmation (reboots required)
- Start optimization process
- Save state before each reboot
- Automatically resume after reboot

### After Each Reboot

**GUI**: Simply run `run-gui.cmd` again and click "Start Optimization"

**CLI**: Run `python main.py` again

The tool will:
- Detect the post-reboot state
- Continue from where it left off
- Run tests on the new configuration
- Proceed to the next optimization step

## Configuration

Edit `config.py` to customize:

```python
# Safety limits
INITIAL_OFFSET = -5          # Conservative starting point
MIN_SAFE_OFFSET = -30        # Maximum undervolt
STEP_SIZE = 5                # Binary search step size

# Test durations
STABILITY_TEST_DURATION = 300   # 5 minutes
IDLE_SAMPLE_DURATION = 30       # 30 seconds
LOAD_SAMPLE_DURATION = 60       # 60 seconds

# Limits
MAX_REBOOT_ATTEMPTS = 100    # Maximum total reboots
```

## State Management

The tool maintains state in `state.json`:
- Current optimization iteration
- Grid values being tested
- Cells already optimized
- Best configuration found
- Test results history

This allows the optimization to survive:
- System reboots
- Crashes
- Power loss
- User interruption

## Output

### Logs
- Detailed logs in `logs/auto_curve_shaper_TIMESTAMP.log`
- Console output with progress updates

### Results
- JSON results files in `results/`
- Contains:
  - Final grid configuration
  - Frequency measurements
  - Stability test results
  - Optimization statistics

### Final Report

```
=== OPTIMIZATION REPORT ===
Status: completed
Total Iterations: 45
Total Reboots: 45
Cells Optimized: 15 / 15
Best Frequency: 5247 MHz
Best Configuration (Iteration 38):
  Min  : -15 -15 -10
  Low  :  -5  -5  -5
  Mid  :  -5  -5  -5
  High : -10 -10 -10
  Max  : -20 -20 -15
```

## Safety Features

- **Conservative Start**: Begins with -5 offset (safe for most CPUs)
- **WHEA Monitoring**: Detects hardware errors (Event ID 19)
- **Stability Testing**: Validates each configuration under stress
- **Automatic Rollback**: Returns to last stable configuration on failure
- **State Persistence**: Can recover from crashes

## Risks & Warnings

⚠️ **Use at your own risk:**
- Aggressive undervolting can cause system instability
- May trigger WHEA errors or crashes
- Could require multiple reboots to recover from bad settings
- Not all CPUs can achieve the same undervolt
- Silicon lottery applies

**Recovery:**
- If system won't boot: Clear CMOS to reset BIOS
- If stuck in boot loop: Boot into Safe Mode and run `csprobe cs-clear -f`
- Emergency: Use `cs-probe/csprobe/run-elevated.ps1` to clear settings

## Requirements

### System Requirements
- AMD Ryzen 9000 (Zen 5) CPU
- Windows 10/11
- Administrator privileges
- 4GB+ free disk space (for logs and results)

### Software Requirements
- Python 3.8 or higher
- cs-probe tools (see configuration)

### Python Dependencies
No external packages required! Uses only Python standard library:
- `tkinter` (GUI, included with Python)
- `threading`, `queue`, `logging`
- `json`, `pathlib`, `subprocess`
- `dataclasses`, `typing`

## Troubleshooting

**Tool doesn't detect admin privileges:**
- Right-click Python and "Run as Administrator"
- Or run from elevated PowerShell/CMD

**csprobe.exe not found:**
- Check path in `config.py` (CSPROBE_EXE)
- Ensure cs-probe is installed

**Frequencies not measured:**
- Check `clocks-sample.ps1` exists
- Verify PowerShell execution policy: `Set-ExecutionPolicy RemoteSigned`

**WHEA errors after boot:**
- Configuration too aggressive
- Tool will detect and roll back
- May need manual recovery with `cs-clear`

## Technical Details

### Binary Search Algorithm

For each cell:
1. Start at conservative offset (-5)
2. Test stability and frequency
3. If stable: try more aggressive (lower) offset
4. If unstable: back off to safer offset
5. Converge to optimal offset (aggressive but stable)

### Optimization Order

Priority order for maximum frequency:
1. **Min row**: Controls low-temperature boost (idle/light load)
2. **Max row**: Controls high-temperature sustained performance
3. **High row**: Medium-high temperature behavior
4. **Low row**: Low-medium temperature behavior  
5. **Mid row**: Medium temperature behavior

### Why Reboots Are Required

CurveShaper settings are:
- Written to ACPI AOD interface (write-only)
- Staged in BIOS
- Applied to SMU during POST (next boot)
- **Not active until reboot**

This is a hardware/BIOS limitation, not a tool limitation.

## Credits

Built on top of:
- **cs-probe**: AMD Zen 5 CurveShaper exploration tool
- **ZenStates-Core**: SMU interface library by irusanov
- **burn.exe**: CPU stress test utility

## License

MIT License - Use at your own risk

---

**Status**: Experimental  
**Last Updated**: 2026-09-03  
**Platform**: AMD Zen 5 (Ryzen 9000) on Windows
