# Auto Curve Shaper — 完整文档

AMD Zen 5 CurveShaper 电压曲线自动优化工具。

- **目标平台**：AMD Ryzen 9000 (Zen 5) 桌面 CPU（9900X3D 实测通过）
- **优化目标**：最高 CPU 频率
- **运行要求**：Windows 10/11、管理员权限、Python 3.8+
- **许可证**：GPL-3.0-or-later — 见 [LICENSE](../../LICENSE)

Other languages / 其他语言：[English documentation](../en/README.md)

---

## 概述

本工具自动探索 CurveShaper 电压曲线空间，找到能让 CPU 频率最大化的设置。
状态全程持久化到磁盘（每次修改 CurveShaper 都需要重启才能生效，工具会在
重启后自动续跑，全程无人值守）。

提供两种优化流程：

| | 标定 → 推导 → 验证（默认） | 经典逐格搜索 |
|---|---|---|
| 策略 | 先建模稳定面，再求解最优网格 | 每格盲搜二分 |
| 重启次数 | 约 8–20 次 | 约 100–200 次 |
| 结果 | 推导网格 + 分工况报告 | 经验收敛网格 |
| 适合 | 可重复、有明确上限的调优 | 榨取最后一点残差频率 |

经典引擎被保留，同时兼任**残差精修**工具（GUI 里的 "refine current grid"）。

## CurveShaper 机制

CurveShaper 是一张 5×3 的电压偏移网格，通过 ACPI AOD 接口写入（BIOS 在
下次 POST 时写入 SMU——运行期完全不生效，且只写不可读）：

| 频率点 | 列 0（约 0 °C） | 列 1（约 50 °C） | 列 2（约 100 °C） |
|---|---|---|---|
| Min | ±30 | ±30 | ±30 |
| Low | ±30 | ±30 | ±30 |
| Mid | ±30 | ±30 | ±30 |
| High | ±30 | ±30 | ±30 |
| Max | ±30 | ±30 | ±30 |

- **行**（Min/Low/Mid/High/Max）跟随内核的*频率/活动*档位：Min 行决定
  空闲/低电流的 boost 行为，Max 行决定单核峰值 boost，High/Max 行决定
  全核持续负载。
- **列**是温度锚点（硬件只接受列索引；标签是近似的）。
- 偏移范围 **−30…+30**（步进 1）。越负 = 电压目标越低；在稳定域内，
  电压越低 ⇒ boost 频率越高。

## v1.5 管线

### 阶段 0 — 标定（建表）

整个网格被设为*统一*偏移，每个档位一次重启（默认 0、−5、−10、−15、
−20、−25、−30）。每次开机后运行**全谱电池**——覆盖频率轴的五个负载
窗口，每个窗口记录 `(偏移, 工况, 频率, 温度, 稳定性, WHEA)`：

| 窗口 | 负载机制 | 频率档位 | 时长 |
|---|---|---|---|
| `idle` | 无负载（频率下沉） | Min 行（低温 boost） | 30 秒 |
| `peak` | Python 忙循环绑核（`SetThreadAffinityMask`） | Max 行（单核 boost） | 90 秒 |
| `allcore` | y-cruncher VT3（burn.exe 回退） | High 行（热态持续负载） | 180 秒 |
| `mid` | 全核负载 + `PROCTHROTTLEMAX=99`（关 boost） | Mid 行（约基础频率） | 90 秒 |
| `low` | 全核负载 + `PROCTHROTTLEMAX=75` | Low 行 | 90 秒 |

由于负载手段都是运行时生效的，**一次重启产出频率轴上五个数据点**——
这就是省重启的根源。全核窗口兼任该档位的稳定性门槛（y-cruncher 判定 +
分窗口 WHEA 统计）。电池中途死机也没关系：剩余窗口会被记为该档位
"失稳"，重启后扫描继续。

这些数据同时填三张表：

- **频率-电压表** —— 各频段在每个偏移下的最大稳定频率
- **频率-温度表** —— 频段内频率与 Tctl 的关系
- **电压-温度表** —— 稳定边界随温度的漂移

可选**归因实验**（`attribute + calibrate` 模式）：扫描前每次重启把一行
CS 设为 +30（其余为 0），把电池结果与 offset-0 基线对比——频率变化
≥100 MHz 的工况就*归因*给该行。这样工况→行的映射是实测的，而非假设。

### 阶段 1 — 推导（求最优网格）

纯逻辑运算（`derive.py`），对每个工况：

```
chosen = 最深稳定偏移 + MARGIN        # 从边界回收一个裕量
chosen = min(chosen, MAX_VOLTAGE_OFFSET)  # 最大偏移上限
chosen = max(chosen, MIN_SAFE_OFFSET)
if 预测频率(chosen) > MAX_FREQ:       # 沿 F-V 曲线往回收
    chosen = 频率恰为 MAX_FREQ 的偏移  #（向零截断，保证不超上限）
if 预测温度(chosen) > MAX_TEMP:       # 警告——CS 偏移救不了温度
```

每行把该工况的偏移写到全部三个温度列（统一偏移扫描暂时分不开列；
残差精修可以后续再拆）。退化情况全部保守处理：

- 某工况全程没有稳定点 → 偏移钉在 Max Offset 上限
- 扫描从未失稳 → 边界标记为 "unbounded"（无界）
- 限频窗口频率没有落到全核窗口以下（限频无效）→ 回退全核边界

### 阶段 2 — 验证

推导网格被写入、重启生效，并真正压测一轮（WHEA + 空闲/负载频率 +
y-cruncher）后才报 `completed`。之后想榨残差，运行
**refine current grid**——逐格二分从当前网格出发，没有格子变化就立即收敛。

## 经典搜索（v1.1–v1.4 流程）

1. 全 0 基线（1 次重启）。
2. 逐格（优先级：Min、Max、High、Low、Mid 行）二分搜索最激进的稳定
   偏移，每格 3–7 次重启。
3. 格子的影响场互相重叠，所以精调扫描会从上一遍最优值出发复测全部
   格子，直到某一遍没有任何变化（±2 死区）或达到 `MAX_SWEEPS`
   （默认 3）。
4. 最终验证：收敛网格重启生效并压测。

GUI 选 "classic search" 进入；选 "refine current grid" 对当前网格重跑
一遍逐格精修。

## 项目结构

```
auto-curve-shaper/
├── gui.py                   # GUI 应用（入口）
├── optimizer.py             # 编排：管线各阶段 + 经典搜索
├── calibration.py           # 全谱电池 + 归因实验
├── derive.py                # 求解器：边界 + 裕量 + 上限 → 5×3 网格
├── workload.py              # 负载电池（绑核 worker、powercfg 限频）
├── temperature_monitor.py   # Tctl 温度遥测（SMN 读取）
├── state_manager.py         # 跨重启状态持久化
├── frequency_monitor.py     # CPU 频率测量
├── utils.py                 # 工具函数与探测工具封装
├── config.py                # 配置参数
├── scripts/
│   └── verify-temp.ps1      # 提权温度采样自检
├── tests/
│   ├── test_derive.py       # 求解器测试（合成数据）
│   └── test_pipeline.py     # 完整管线状态机（模拟硬件）
├── docs/                    # 本文档（en/ + zh/）
├── run-gui.cmd / run-gui.ps1
├── state.json               # 运行状态（自动生成，已 gitignore）
├── results/                 # 测试结果（自动生成，已 gitignore）
└── logs/                    # 执行日志（自动生成，已 gitignore）
```

## 使用方法

### 前置条件

1. AMD Ryzen 9000 (Zen 5) CPU，Windows 10/11
2. Python 3.8+（自带 tkinter）
3. 外部 SMU 探测工具链（CurveShaper 写入与 SMN 读取，仓库不附带）——
   通过 `CS_PROBE_DIR` 环境变量（`setx CS_PROBE_DIR "<目录>"`）或项目内
   `probe-tools/` 文件夹指向它
4. y-cruncher（推荐）：从
   [numberworld.org](https://www.numberworld.org/y-cruncher/) 下载
   Windows x64 版，解压到项目的 `y-cruncher\` 文件夹。没有它工具会回退
   到 burn.exe——只能检测崩溃，检测不了计算错误。
5. 先提权运行一次 `scripts\verify-temp.ps1`，确认你主板上的 Tctl 遥测
   可用。

### 运行

右键 `run-gui.cmd` → **以管理员身份运行**（或在提权 PowerShell 里运行
`run-gui.ps1`）。

**Pipeline & Limits** 面板：

- **Mode** —— `calibrate`（默认管线）、`attribute + calibrate`
  （多 5 次归因探针重启）、`classic search`、`refine current grid`
- **Max Temp (°C)** —— 温度上限，默认 90
- **Max Freq (MHz, 0=off)** —— 频率上限；求解器会沿 F-V 曲线回收，
  保证任何频段不超过它
- **Max Offset (+V cap)** —— 推导偏移的上限；0 表示禁止正偏移（加压）
- **Safety Margin** —— 距稳定边界的回收量（偏移单位，默认 10）

点 **Start** 之后全程无人值守：

- 每个需要重启的步骤：60 秒可取消倒计时（"Cancel Reboot"），然后
  `shutdown /r`
- 登录时，计划任务以提权方式带 `--continue` 重新拉起 GUI；10 秒倒计时
  后自动续跑（关窗即中止）。运行结束后任务自动注销。
- 想手动重启：`config.py` 里设 `AUTO_REBOOT = False`。

中途干预：**Stop** 杀掉压力负载（运行在下一个重启节点停下）、
**Reset State** 清空进度、**Exit** 取消挂起的倒计时和关机。

### 重启之后

什么都不用做。工具自动检测重启后状态并继续。中断的运行（崩溃、断电）
从 `state.json` 恢复；如果崩溃发生在标定电池中途，没跑到的窗口会被记为
该档位失稳，扫描继续推进。

## 配置速查（`config.py`）

```python
CALIB_OFFSETS = [0, -5, -10, -15, -20, -25, -30]  # 扫描档位（重启次数）
CALIB_REGIMES = ["idle", "peak", "allcore", "mid", "low"]
CALIB_ALLCORE_DURATION = 180     # 每档 y-cruncher 门槛时长（秒）
MID_THROTTLE_PCT = 99            # 最高处理器状态 99% = 关 boost
LOW_THROTTLE_PCT = 75
CALIB_MARGIN = 10                # 距边界的裕量（偏移单位）
MAX_TEMP_LIMIT = 90              # 上限，GUI 可覆盖
MAX_FREQ_LIMIT = 0               # 0 = 不限
MAX_VOLTAGE_OFFSET = 0           # 禁止正偏移
STABILITY_TEST_DURATION = 300    # 经典模式压测窗口
MAX_SWEEPS = 3                   # 经典模式精调遍数上限
MAX_REBOOT_ATTEMPTS = 350        # 硬上限
AUTO_REBOOT = True               # False = 手动重启
```

## 状态与输出

- `state.json` —— 完整运行状态（原子写入，可从崩溃恢复；文件损坏会
  自动备份）。删掉它 = 全新开始。
- `results/` —— JSON 测试结果、最终网格。
- `logs/` —— 按时间戳的日志、y-cruncher 输出、分窗口频率 CSV。
- GUI 实时显示网格状态、标定进度（档位 × 窗口）、模式、上限、最佳频率。

## 故障排除

| 症状 | 处理 |
|---|---|
| WinRing0 驱动初始化失败 / "Administrator Required" | 以管理员身份运行 GUI（右键 `run-gui.cmd`） |
| 找不到探测工具可执行文件 | 检查 `config.py` 的 `CS_PROBE_DIR` / `CSPROBE_EXE` |
| 频率测不到 | 检查 `clocks-sample.ps1`；`Set-ExecutionPolicy RemoteSigned` |
| "no Tctl samples" | 提权运行 `scripts\verify-temp.ps1`；部分主板需要更新探测工具版本 |
| 重启后出现 WHEA 错误 | 该档位太激进——工具会自动回退；手动恢复：执行探测工具的 `cs-clear -f` 后重启 |
| 激进档位后开不了机 | 清 CMOS；然后用探测工具链的提权运行器执行 `cs-clear -f` |
| mid/low 窗口频率还是全核 boost 水平 | 此电源计划下 PROCTHROTTLEMAX 无效——求解器会检测到（该工况标记"无效"）并回退全核边界 |

## 安全机制

- 保守起步，每个标定档位都有稳定性门槛
- WHEA Event-19 监控，按测试窗口归因
- 失稳配置自动回退
- 崩溃安全的状态持久化（原子写入、损坏备份）
- 上限在推导时强制执行；温度上限达不到会明确报告，绝不静默忽略

## 风险与警告

⚠️ **风险自担。** 激进欠压可能导致不稳定、WHEA 错误，或需要清 CMOS
才能恢复的开机失败。硅质彩票客观存在，不是所有 CPU 都吃同样的偏移。
请在测试机器上运行，盯紧温度，第一次标定不要在生产机上无人值守进行。

## 致谢

构建于 **ZenStates-Core**（irusanov，SMU 接口）、**y-cruncher**
（Xavier Gagnon，稳定性测试）与 SkatterBencher 的 Curve Shaper 实测数据
之上。

## 许可证

Copyright (C) 2026 Auto Curve Shaper Contributors.

本程序为自由软件：你可以在自由软件基金会发布的 GNU 通用公共许可证
（第 3 版或你选择的更高版本）条款下重新分发和/或修改它。详见
[LICENSE](../../LICENSE)。

本程序按"现状"提供，不附带任何担保（包括适销性与特定用途适用性的
默示担保）。详情参见 GNU 通用公共许可证全文。
