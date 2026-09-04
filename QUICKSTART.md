# Quick Start Guide

快速开始使用 Auto Curve Shaper 优化你的 AMD Zen 5 CPU 电压曲线。

## 5 分钟快速设置

### 1. 检查系统要求 ✓

- [ ] AMD Ryzen 9000 (Zen 5) CPU
- [ ] Windows 10/11
- [ ] Python 3.8+ 安装
- [ ] 管理员权限

### 2. 配置 cs-probe 路径

打开 `config.py`，确认路径正确：

```python
CS_PROBE_DIR = Path(r"C:\Users\deepi\.zcode\workspace\default\cs-probe")
```

如果 cs-probe 在其他位置，修改此路径。

### 3. 运行测试（可选）

验证工具能正常工作：

```bash
# 测试 csprobe 连接
cd <cs-probe-dir>
.\csprobe\csprobe.exe info

# 测试频率监测
.\clocks-sample.ps1 10
```

压力测试使用 **y-cruncher**（能检测计算错误，比单纯的崩溃检测强）：
默认从 `y-cruncher\y-cruncher.exe` 加载（未安装时自动回退到 burn.exe，仅崩溃检测）。
安装：从 https://www.numberworld.org/y-cruncher/ 下载 Windows x64 版，
解压到项目目录下的 `y-cruncher\` 文件夹即可。

### 4. 首次运行

```bash
# 右键 run-gui.cmd → "以管理员身份运行"
```

或

```bash
# 以管理员身份运行 PowerShell
powershell -ExecutionPolicy Bypass -File run-gui.ps1
```

### 5. 开始优化

点击 "Start Optimization" 按钮，在确认对话框中点击 "是"。

工具会：
- 清除所有 CurveShaper 单元格（设为 0）
- 保存状态
- 提示重启

### 6. 重启后继续（全自动）

点 Start Optimization 后整个循环无人值守：

1. 工具测完一个配置 → **60 秒倒计时后自动重启**（GUI 上有 "Cancel Reboot" 按钮，在电脑前需要保存东西时点它暂停节奏）
2. 重启后登录，计划任务自动弹出 GUI
3. **10 秒倒计时后自动继续优化**（关闭窗口可中止）
4. 循环直到完成；完成/停止/重置后自启任务自动注销

也可以全手动：`config.py` 里设 `AUTO_REBOOT = False`，之后每次自己重启 + 打开工具点 Start。

工具会自动：
- 检测重启状态
- 运行测试（频率测量 + 稳定性）
- 调整搜索范围
- 设置下一个测试值
- 提示再次重启

重复此过程直到优化完成。整个过程分多遍扫描（sweep）：第一遍逐格搜索，
之后每遍从上一遍的最优值出发复测所有格子，直到某一遍没有任何格子变化
（典型共 2 遍，上限可在 `config.py` 的 `MAX_SWEEPS` 调整），总计约
100-200 次重启。

## 理解优化过程

### 阶段 1: 基线测试（1 次重启）
- 所有偏移 = 0
- 测量基准频率

### 阶段 2: 第一遍扫描（3-7 次重启/单元格）
每个单元格：
1. 测试初始偏移 (-5)
2. 如果稳定 → 尝试更激进的值 (-10, -15, ...)
3. 如果不稳定 → 回退到安全值
4. 二分搜索收敛到最优值

### 阶段 3: 精调扫描（每遍 3-7 次重启/单元格）
CurveShaper 各格子的影响场互相重叠，逐格优化后邻居的值会影响本格最优解：
- 第二遍从每个格子的第一遍最优值出发重新二分（省去重复探索）
- 某遍扫描没有任何格子变化 → 已收敛，停止
- 最多 `MAX_SWEEPS` 遍（默认 3，可在 config.py 调整；设为 1 = 关闭精调）

**优化顺序**：
1. Min 行（低温提升）- 3 个单元格
2. Max 行（高温性能）- 3 个单元格
3. High 行 - 3 个单元格
4. Low 行 - 3 个单元格
5. Mid 行 - 3 个单元格

### 阶段 4: 最终验证（1 次重启）
- 应用最佳配置
- 完整稳定性测试

## 监控进度

### GUI 显示
- **状态**：当前阶段
- **Iteration**：当前迭代次数
- **Reboots**：已重启次数
- **Cells Optimized**：已完成单元格数 / 15
- **Best Frequency**：目前找到的最高频率
- **Sweep**：当前扫描遍数 / 上限（第 1 遍为逐格搜索，之后为精调）
- **网格**：5×3 单元格，颜色编码：
  - 🟨 黄色：正在优化
  - 🟩 绿色：已优化
  - 🟦 蓝色：已修改
  - ⬜ 白色：默认值

### 日志输出（GUI Log 面板）
```
=== Optimizing Cell [Min, 0C] - Iteration 5 ===
Testing offset -10...
Idle measurement: CCD0=4560 MHz, CCD1=4008 MHz
Load measurement: CCD0=4853 MHz, CCD1=4543 MHz
Stability test PASSED
Offset -10 is STABLE (freq: 4853 MHz)
```

## 常见场景

### 场景 1: 第一次运行
```
Status: Not Started
→ Click "Start Optimization"
→ Confirm dialog
→ "Please reboot and run again"
→ Reboot
```

### 场景 2: 重启后继续（无人值守）
```
Status: Waiting Reboot
→ 60s 倒计时后自动重启（Cancel Reboot 可暂停）
→ 登录后 GUI 自动打开
→ 10s 倒计时后自动继续测试
→ 循环，直到 15 格全部优化完成
```

### 场景 3: 优化完成
```
Status: Completed
Cells Optimized: 15 / 15
Best Frequency: 5247 MHz
→ View final report
→ Results saved to results/ directory
```

### 场景 4: 中断恢复
如果：
- 系统崩溃
- 停电
- 用户中断

只需：
1. 重启系统
2. 再次运行工具
3. 从上次保存的状态继续

## 预期时间

| 阶段 | 重启次数 | 时间（每次重启 5 分钟） |
|------|---------|----------------------|
| 基线 | 1 | 5 分钟 |
| 第一遍扫描（15 单元格） | 46-106 | 3.8 - 8.8 小时 |
| 精调扫描（典型 1 遍，≤2 遍） | 16-60 / 遍 | 1.3 - 5 小时 / 遍 |
| 最终验证 | 1 | 5 分钟 |
| **总计（典型 2 遍）** | **~63-167** | **5 - 14 小时** |

*精调遍数取决于格子间相互作用的强弱；某遍全部无变化即提前收敛。上限 `MAX_SWEEPS`，重启硬上限 `MAX_REBOOT_ATTEMPTS`。*

## 故障排除

### ❌ "csprobe.exe not found"
→ 检查 `config.py` 中的 `CSPROBE_EXE` 路径

### ❌ "Administrator privileges required"
→ 右键 → "以管理员身份运行"

### ❌ "No frequencies parsed"
→ 检查 `clocks-sample.ps1` 是否存在
→ 运行：`Set-ExecutionPolicy RemoteSigned`

### ❌ 重启后系统不稳定
→ 工具会检测 WHEA 错误并自动回退
→ 手动恢复：运行 `csprobe cs-clear -f` 然后重启

### ⚠️ "Offset -20 is UNSTABLE"
→ 这是正常的！工具在探索极限
→ 会自动回退到安全值

## 安全提示

✅ **Do**:
- 从默认设置开始
- 保存重要工作
- 定期备份 `state.json`
- 监控 WHEA 错误日志

❌ **Don't**:
- 修改 `MIN_SAFE_OFFSET` 超过 -30
- 在优化期间关闭 WHEA 错误检测
- 跳过稳定性测试
- 在生产环境运行（使用测试机器）

## 下一步

完成优化后：
1. 记录最佳配置（查看 `results/` 目录）
2. 在 HYDRA 或其他工具中手动验证
3. 运行更长时间的稳定性测试
4. 分享你的结果！

---

**需要帮助？** 查看 [README.md](README.md) 完整文档或提交 Issue。
