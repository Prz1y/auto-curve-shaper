# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-03

### Added
- Initial release of Auto Curve Shaper
- Core optimization engine with binary search algorithm
- Reboot-persistent state management
- Frequency monitoring (idle and load)
- Stability testing with WHEA error detection
- Modern GUI with real-time progress display
- 5×3 CurveShaper grid visualization
- CLI mode for command-line usage
- Comprehensive documentation (README, QUICKSTART, CONTRIBUTING)
- Launch scripts for both GUI and CLI modes
- Administrator privilege checking
- Automatic state recovery after reboot
- Configurable optimization parameters
- Result logging and reporting

### Features
- **Optimization Target**: Maximum CPU frequency
- **Algorithm**: Binary search per cell with stability validation
- **Grid Size**: 5 rows × 3 columns (15 cells total)
- **Offset Range**: -30 to +30 (starts conservatively at -5)
- **Optimization Order**: Min → Max → High → Low → Mid rows
- **Safety**: WHEA error detection, automatic rollback, conservative limits
- **GUI**: Real-time grid display, progress tracking, log output
- **CLI**: Detailed console output, status reporting
- **Persistence**: JSON state file survives crashes and power loss

### Technical Details
- Python 3.8+ (standard library only, no external dependencies)
- Tkinter GUI (included with Python)
- Windows-only (ACPI AOD WMI interface)
- AMD Zen 5 (Ryzen 9000) support
- Integration with cs-probe tools
- Automatic reboot cycle management

### Documentation
- README.md: Complete project documentation
- QUICKSTART.md: 5-minute setup guide
- CONTRIBUTING.md: Contribution guidelines
- GITHUB_SETUP.md: Git and GitHub setup instructions
- PROJECT_SUMMARY.md: Project completion summary
- LICENSE: MIT License

### Known Limitations
- Requires manual reboot between iterations
- Windows-only (cs-probe limitation)
- Single-threaded optimization
- Requires cs-probe external tools
- AMD Zen 5 only (not tested on other architectures)

### System Requirements
- AMD Ryzen 9000 (Zen 5) CPU
- Windows 10/11
- Python 3.8 or higher
- Administrator privileges
- cs-probe tools

---

## [Unreleased]

### Planned Features
- Automatic reboot support (startup task)
- Unit test suite
- CI/CD pipeline
- Faster testing mode
- Multi-CPU model support validation
- Result visualization charts
- Configuration import/export
- Remote monitoring capability

### Potential Enhancements
- Additional optimization targets (power, efficiency)
- Machine learning prediction
- Web UI option
- Linux support (if feasible)
- Multi-threaded parallel testing

---

## Version History

- **v1.0.0** (2026-09-03): Initial release with full feature set
- **v0.9.0** (2026-09-03): Beta testing version (internal)
- **v0.5.0** (2026-09-03): Core engine completion
- **v0.1.0** (2026-09-03): Project initialization

---

## Migration Guide

### From cs-probe Manual Testing

If you were manually testing CurveShaper values with cs-probe:

1. **Backup your current settings**:
   ```bash
   # Record your current HYDRA or manual settings
   ```

2. **Clear existing settings**:
   ```bash
   csprobe cs-clear -f
   ```

3. **Run Auto Curve Shaper**:
   ```bash
   python gui.py  # or python main.py
   ```

4. **Compare results**:
   - Manual settings: Check your recorded values
   - Auto settings: Check `results/` directory
   - Validate in HYDRA or with longer stability tests

### State File Format

The `state.json` file structure:
```json
{
  "iteration": 15,
  "total_reboots": 45,
  "current_grid": [[...], ...],
  "best_grid": [[...], ...],
  "best_frequency": 5247.0,
  "cells_optimized": [...],
  "current_cell": [row, col],
  "search_min": -30,
  "search_max": 0,
  "search_current": -15,
  "best_stable_offset": -20,
  "status": "running",
  "current_phase": "optimize_min"
}
```

---

## Credits

### Built On
- **cs-probe**: AMD Zen 5 CurveShaper exploration tool
- **ZenStates-Core**: SMU interface library by irusanov
- **burn.exe**: CPU stress testing utility

### Inspired By
- HYDRA: Visual CurveShaper interface
- CoreCycler: CPU stability testing methodology
- AMD Ryzen Master: Official overclocking tool

### Special Thanks
- AMD for Zen 5 architecture
- Community testers and early adopters
- Open-source contributors

---

## License

MIT License - See LICENSE file for details

Copyright (c) 2026 Auto Curve Shaper Contributors
