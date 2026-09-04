# 快速开始

五分钟内让 Auto Curve Shaper 在你的 AMD Zen 5 CPU 上跑起来。

返回：[完整文档](README.md) · [English Quick Start](../en/QUICKSTART.md)

---

## 5 分钟快速设置

### 1. 检查系统要求 ✓

- [ ] AMD Ryzen 9000 (Zen 5) CPU
- [ ] Windows 10/11
- [ ] Python 3.8+ 已安装
- [ ] 管理员账户

### 2. 配置 SMU 探测工具链路径

该工具链（CurveShaper 写入 + SMN 读取）**不随本仓库分发**。两种方式
二选一：

```powershell
setx PROBE_TOOLS_DIR "D:\工具链目录"   # 机器级环境变量（推荐）
```

或把工具链放进项目内的 `probe-tools\` 文件夹。

### 3. 验证链路（可选，但建议做）

```powershell
# 提权 PowerShell，项目目录
# Tctl 温度遥测自检（本项目自带脚本）
powershell -ExecutionPolicy Bypass -File scripts\verify-temp.ps1
```

首次标定前，另请运行探测工具链自带的 info / 频率采样命令，确认 SMU
访问正常。

压力测试使用 **y-cruncher**（能检测计算错误，比 burn.exe 的纯崩溃检测
强）：从 <https://www.numberworld.org/y-cruncher/> 下载 Windows x64 版，
解压到项目目录下的 `y-cruncher\` 文件夹。没装的话工具自动回退 burn.exe。

### 4. 首次运行

右键 `run-gui.cmd` → **以管理员身份运行**。

### 5. 选模式、开始

在 **Pipeline & Limits** 面板里：

- 保持 **calibrate**（推荐；约 8–14 次重启 + 一轮验证），或选
  `attribute + calibrate`（多 5 次归因探针重启）、`classic search`
  （约 100–200 次重启）、`refine current grid`
- 设置上限：**Max Temp**（°C）、**Max Freq**（MHz，0 = 不限）、
  **Max Offset**（正偏移上限）、**Safety Margin**（安全裕量）

点 **Start Optimization** 并确认。

## 接下来会发生什么

从这里开始全程无人值守：

1. 每个标定档位跑约 10 分钟的负载窗口（空闲 → 绑核单核 → 全核
   y-cruncher → 两个限频频段）。
2. GUI 倒计时 60 秒（需要保存东西就点 **Cancel Reboot**），随后自动重启。
3. 登录后计划任务自动拉起 GUI；10 秒倒计时后自动续跑（关窗即中止）。
4. 档位扫完后，工具推导最优网格，重启生效并压测一轮，然后报
   **Completed**。

想手动重启？`config.py` 里设 `AUTO_REBOOT = False`，之后每轮自己重启 +
点 Start。

## 监控进度

状态面板显示迭代/重启计数、最佳频率，以及管线进度行
（`Calibration: 3/7 offset levels | level -10, window 2/5`）。
网格颜色：🟨 测试中 · 🟩 已优化 · 🟦 已修改 · ⬜ 默认。

典型标定时间线（重启约 2 分钟，每档会话约 10 分钟）：

| 阶段 | 重启次数 |
|---|---|
| 标定档位（7 × 全谱电池） | 7 |
| 最终验证（推导网格） | 1–2 |
| 可选残差精修 | 0–15 |

经典搜索的代价：第一遍 46–106 次重启，之后每遍精调 16–60 次。

## 常见场景

- **第一次运行** —— Start → 确认 → 工具暂存第一个档位并请求重启；
  之后全自动。
- **崩溃 / 断电** —— 重启并重新打开（或等自动续跑）：从 `state.json`
  恢复。崩溃发生在电池中途时，没跑到的窗口按失稳记账，扫描继续。
- **完成** —— `Status: Completed`；最终网格和分工况报告在日志和
  `results/` 里。

## 故障排除

| 症状 | 处理 |
|---|---|
| "Administrator privileges required" / WinRing0 初始化失败 | 提权运行 |
| 找不到探测工具可执行文件 | 检查 `config.py` 里的 `PROBE_TOOLS_DIR` |
| "No frequencies parsed" | 检查 `clocks-sample.ps1`；`Set-ExecutionPolicy RemoteSigned` |
| "no Tctl samples" | 提权运行 `scripts\verify-temp.ps1` |
| 重启后不稳定 | 工具自动回退；手动：探测工具 `cs-clear -f` + 重启 |
| "Offset -20 is UNSTABLE" | 正常现象——扫描正在探测极限 |

## 安全提示

✅ 从默认设置开始 · 开始前保存工作 · 备份 `state.json` · 盯 WHEA 日志
❌ 不要把 `MIN_SAFE_OFFSET` 改到 −30 以下 · 不要关 WHEA 监控 ·
第一次标定不要在生产机上跑

## 下一步

1. 记录最终网格（日志 + `results/`）
2. 用 HYDRA 或 Ryzen Master 交叉验证
3. 跑长时间稳定性测试（30 分钟以上 y-cruncher）
4. 阅读 [CALIBRATION.md](CALIBRATION.md) 了解求解器做了什么

---

需要帮助？查看[完整文档](README.md)或提交 Issue。
