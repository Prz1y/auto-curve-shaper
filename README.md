# Auto Curve Shaper

Automatic AMD Zen 5 CurveShaper voltage-curve optimization tool.
AMD Zen 5 CurveShaper 电压曲线自动优化工具。

| | |
|---|---|
| Platform / 平台 | AMD Ryzen 9000 (Zen 5) · Windows 10/11 · Administrator |
| Goal / 目标 | Maximum CPU frequency / 最高 CPU 频率 |
| Version / 版本 | v1.5.0 |
| License / 许可证 | **GPL-3.0-or-later** |

---

## v1.5 — Model-first pipeline / 建模优先管线

**EN** — Instead of blind per-cell search, the tool first *calibrates* three
tables (frequency–voltage, frequency–temperature, voltage–temperature) with
one reboot per offset level, then *derives* the optimal 5×3 grid from
stability boundaries and user limits (max temperature, max frequency, max
voltage offset), and finally *verifies* it with a real post-reboot stress
test. Total cost: **~8–20 reboots** instead of 100–200.

**中文** — 不再盲目逐格搜索：每个偏移档位一次重启，先*标定*三张表
（频率-电压、频率-温度、电压-温度），再根据稳定边界与用户上限
（最高温度、最高频率、最大电压偏移）*推导*最优 5×3 网格，最后真正重启
进去做压力*验证*。全程约 **8–20 次重启**，而非常规搜索的 100–200 次。

## Documentation / 文档

| English | 中文 |
|---|---|
| [Full documentation](docs/en/README.md) | [完整文档](docs/zh/README.md) |
| [Quick start](docs/en/QUICKSTART.md) | [快速开始](docs/zh/QUICKSTART.md) |
| [Calibration pipeline deep-dive](docs/en/CALIBRATION.md) | [标定管线详解](docs/zh/CALIBRATION.md) |
| [Probe implementation notes](docs/en/PROBE.md) | [探测工具实现说明](docs/zh/PROBE.md) |
| [Contributing](docs/en/CONTRIBUTING.md) | [参与贡献](docs/zh/CONTRIBUTING.md) |
| [Changelog](CHANGELOG.md) | [更新日志](CHANGELOG.md) |

## Quick start / 快速开始

**EN** — Right-click `run-gui.cmd` → **Run as Administrator**, pick a mode
and set the limits in the "Pipeline & Limits" panel, click **Start**. The
run is fully unattended across reboots (auto-reboot countdown + logon
auto-continue via Task Scheduler).

**中文** — 右键 `run-gui.cmd` → **以管理员身份运行**，在 "Pipeline &
Limits" 面板选择模式并设置上限，点击 **Start**。整个流程跨重启全自动
（自动重启倒计时 + 计划任务登录自启续跑）。

## Safety / 安全

⚠️ **EN** — Aggressive undervolting can crash the system, trigger WHEA
errors, or require a CMOS reset to recover. Use at your own risk, ideally on
a test machine. Read the safety section in the documentation before starting.

⚠️ **中文** — 激进欠压可能导致系统崩溃、触发 WHEA 错误，甚至需要清
CMOS 才能恢复。风险自担，建议在测试机器上使用。开始前请阅读文档中的
安全章节。

## License / 许可证

This project is licensed under the **GNU General Public License v3.0 or
later (GPL-3.0-or-later)** — see [LICENSE](LICENSE).
本项目基于 **GPL-3.0-or-later** 许可证开源，详见 [LICENSE](LICENSE)。

Built on top of / 基于: [ZenStates-Core](https://github.com/irusanov/ZenStates-Core) ·
[y-cruncher](https://www.numberworld.org/y-cruncher/)
