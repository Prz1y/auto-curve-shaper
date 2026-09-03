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

# 测试烧机工具
.\burn\burn.exe
# (Ctrl+C 停止)
```

### 4. 首次运行

#### 使用 GUI（推荐）

```bash
# 右键 run-gui.cmd → "以管理员身份运行"
```

或

```bash
# 以管理员身份运行 PowerShell
powershell -ExecutionPolicy Bypass -File run-gui.ps1
```

#### 使用 CLI

```bash
# 右键 run.cmd → "以管理员身份运行"
```

### 5. 开始优化

1. **GUI**: 点击 "Start Optimization" 按钮
2. **CLI**: 按照提示输入 `yes` 确认

工具会：
- 清除所有 CurveShaper 单元格（设为 0）
- 保存状态
- 提示重启

### 6. 重启后继续

每次重启后：
1. **GUI**: 再次运行 `run-gui.cmd`，点击 "Start Optimization"
2. **CLI**: 再次运行 `run.cmd`

工具会自动：
- 检测重启状态
- 运行测试（频率测量 + 稳定性）
- 调整搜索范围
- 设置下一个测试值
- 提示再次重启

重复此过程直到优化完成（约 50-100 次重启）。

## 理解优化过程

### 阶段 1: 基线测试（1 次重启）
- 所有偏移 = 0
- 测量基准频率

### 阶段 2: 单元格优化（3-7 次重启/单元格）
每个单元格：
1. 测试初始偏移 (-5)
2. 如果稳定 → 尝试更激进的值 (-10, -15, ...)
3. 如果不稳定 → 回退到安全值
4. 二分搜索收敛到最优值

**优化顺序**：
1. Min 行（低温提升）- 3 个单元格
2. Max 行（高温性能）- 3 个单元格
3. High 行 - 3 个单元格
4. Low 行 - 3 个单元格
5. Mid 行 - 3 个单元格

### 阶段 3: 最终验证（1 次重启）
- 应用最佳配置
- 完整稳定性测试

## 监控进度

### GUI 显示
- **状态**：当前阶段
- **Iteration**：当前迭代次数
- **Reboots**：已重启次数
- **Cells Optimized**：已完成单元格数 / 15
- **Best Frequency**：目前找到的最高频率
- **网格**：5×3 单元格，颜色编码：
  - 🟨 黄色：正在优化
  - 🟩 绿色：已优化
  - 🟦 蓝色：已修改
  - ⬜ 白色：默认值

### CLI 输出
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

### 场景 2: 重启后继续
```
Status: Waiting Reboot
→ Run GUI/CLI again
→ Click "Start Optimization" / Confirm
→ Tests run automatically
→ "Please reboot and run again"
→ Reboot
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
| Min 行（3 单元格） | 9-21 | 45 分钟 - 1.75 小时 |
| Max 行（3 单元格） | 9-21 | 45 分钟 - 1.75 小时 |
| High 行（3 单元格） | 9-21 | 45 分钟 - 1.75 小时 |
| Low 行（3 单元格） | 9-21 | 45 分钟 - 1.75 小时 |
| Mid 行（3 单元格） | 9-21 | 45 分钟 - 1.75 小时 |
| 最终验证 | 1 | 5 分钟 |
| **总计** | **46-106** | **3.8 - 8.8 小时** |

*实际时间取决于 CPU 体质和每个单元格的搜索收敛速度*

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
