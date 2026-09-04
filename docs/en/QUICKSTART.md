# Quick Start

Get Auto Curve Shaper running on your AMD Zen 5 CPU in about five minutes.

Back to: [Full documentation](README.md) · [中文快速开始](../zh/QUICKSTART.md)

---

## 5-minute setup

### 1. Check requirements ✓

- [ ] AMD Ryzen 9000 (Zen 5) CPU
- [ ] Windows 10/11
- [ ] Python 3.8+ installed
- [ ] Administrator account

### 2. Point the tool at the SMU probe toolchain

Open `config.py` and set `CS_PROBE_DIR` to the directory of your SMU
probe toolchain (CurveShaper writes + SMN reads). The toolchain is
**not bundled** with this repository.

### 3. Verify the plumbing (optional but recommended)

```powershell
# elevated PowerShell, project directory
# Tctl telemetry self-test (this project's script)
powershell -ExecutionPolicy Bypass -File scripts\verify-temp.ps1
```

Also run your probe toolchain's own info / frequency-sampling commands to
confirm SMU access before the first calibration.

Stress testing uses **y-cruncher** (detects computation errors, unlike
burn.exe's crash-only detection): download the Windows x64 build from
<https://www.numberworld.org/y-cruncher/> and unpack it into the project's
`y-cruncher\` folder. Without it the tool falls back to burn.exe.

### 4. First run

Right-click `run-gui.cmd` → **Run as administrator**.

### 5. Pick a mode and start

In the **Pipeline & Limits** panel:

- keep **calibrate** (recommended; ~8–14 reboots + a verification pass), or
  pick `attribute + calibrate` (+5 probe reboots), `classic search`
  (~100–200 reboots), or `refine current grid`
- set the caps: **Max Temp** (°C), **Max Freq** (MHz, 0 = unlimited),
  **Max Offset** (positive-voltage cap), **Safety Margin**

Click **Start Optimization** and confirm.

## What happens next

Fully unattended from here:

1. Each calibration level runs ~10 minutes of load windows (idle → pinned
   single-core → all-core y-cruncher → two throttled bands).
2. The GUI counts down 60 s (click **Cancel Reboot** if you need to save
   work), then the machine reboots itself.
3. At logon a scheduled task relaunches the GUI; after a 10 s countdown the
   run resumes automatically (closing the window aborts).
4. After the last level the tool derives the optimal grid, reboots into it,
   and stress-tests it before reporting **Completed**.

Prefer manual reboots? Set `AUTO_REBOOT = False` in `config.py` — then you
reboot and click Start yourself each round.

## Monitoring progress

The status panel shows iteration / reboot counters, best frequency, and a
pipeline line (`Calibration: 3/7 offset levels | level -10, window 2/5`).
The grid colors: 🟨 testing · 🟩 optimized · 🟦 modified · ⬜ default.

Typical calibration timeline (reboot ≈ 2 min, sessions ≈ 10 min):

| Stage | Reboots |
|---|---|
| Calibration levels (7 × battery) | 7 |
| Final validation (derived grid) | 1–2 |
| Optional residual refinement | 0–15 |

Classic search instead costs 46–106 reboots for the first pass plus 16–60
per refinement sweep.

## Common scenarios

- **First run** — Start → confirm → the tool stages the first level and
  asks for the reboot; everything after that is automatic.
- **Crash / power loss** — reboot and relaunch (or let the auto-continue do
  it): the run resumes from `state.json`. A crash *during* a battery credits
  the un-run windows as unstable and moves on.
- **Finished** — `Status: Completed`; find the derived grid and per-regime
  report in the log and `results/`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Administrator privileges required" / WinRing0 init fail | Run elevated |
| Probe executable not found | Fix `CS_PROBE_DIR` in `config.py` |
| "No frequencies parsed" | Check `clocks-sample.ps1`; `Set-ExecutionPolicy RemoteSigned` |
| "no Tctl samples" | Run `scripts\verify-temp.ps1` elevated |
| Unstable after reboot | The tool rolls back automatically; manual: the probe's `cs-clear -f` + reboot |
| "Offset -20 is UNSTABLE" | Normal — the sweep is probing the limits |

## Safety do / don't

✅ Start from defaults · save your work before starting · keep `state.json`
backups · watch WHEA logs
❌ Don't push `MIN_SAFE_OFFSET` beyond −30 · don't disable WHEA monitoring ·
don't run the first calibration on a production machine

## Next steps

1. Record the final grid (log + `results/`)
2. Cross-check in HYDRA or Ryzen Master
3. Run a long stability test (30+ min y-cruncher)
4. Read [CALIBRATION.md](CALIBRATION.md) to understand what the solver did

---

Need help? Check the [full documentation](README.md) or open an issue.
