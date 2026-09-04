# SMU 探测工具（`acsprobe`）— 实现说明

面向维护者和好奇者的外部探测工具说明。该工具是一个单文件 C# 命令行
程序（基于 irusanov 的 ZenStates-Core 驱动库构建），只暴露本项目所需的
硬件访问能力。它随工具链分发——不属于本仓库。

其他语言 / Other language: [English version](../en/PROBE.md)

---

## 本项目用到的命令

| 命令 | 用途 |
|---|---|
| `acsprobe cs-set <行> <列> <偏移> -f` | 暂存一个 CurveShaper 单元格 |
| `acsprobe cs-clear -f` | 全部 15 格暂存为 0 |
| `acsprobe read <smn十六进制>` | 读一个 SMN 双字（Tctl 温度） |
| `acsprobe info` / `co-get` | 环境自检（CPU/SMU 信息、每核 CO 读回） |

## CurveShaper 写入路径

- **接口**：ACPI AOD WMI 命名空间 `root\wmi`，类 `AMD_ACPI`，实例
  `ACPI\PNP0C14\AOD_0`。CurveShaper 不走任何 SMU 邮箱。
- **对象**：`0x00020059`（"Set Curve Shaper"）；接受范围 −30…+30，
  步进 1。
- **帧格式**：`RunCommand(Inbuf[8])` —— 外层序列
  `Start(0x00040001, 0)` → N 条 `{ObjectId u32 LE, Value u32 LE}` →
  `End(0x00040002, 0)`。
- **值编码**：`value = (idx << 8) | (offset & 0xFF)`，其中
  `idx = row*3 + col`（行 0–4 = Min/Low/Mid/High/Max 频率点；列 0–2 =
  冷/中/热温度锚点），负偏移用补码（−30 → 0xE2）。
- **语义**：只写暂存（write-through staging）——BIOS 在下次 POST 时把
  暂存网格写进 SMU。运行期无任何效果，且不可读回（查询对象恒返回 0）：
  实际生效状态只能从行为（频率/VID 变化）或厂商工具推断。这就是每次
  改网格都要花一次重启的原因。

## SMN 读取路径（温度）

- `acsprobe read 0x59800` 返回 Tctl 原始双字；
  `Tctl(°C) = (raw >> 21) × 0.125 − 49`。
- 访问经 WinRing0/ZenStates-Core 内核驱动完成，因此调用进程必须提权；
  否则驱动启动失败（表现为 `INIT-FAIL` / `TemperatureError`）。
- 每次读取一个进程 ⇒ 采样率上限约 2.4 Hz，对标定电池的分窗口温度统计
  绰绰有余。

## 每核 Curve Optimizer（本工具暂未使用）

`co-set` / `co-get` 走 RSMU 邮箱（0x06 写 / 0xD5 读），**按核**生效且
**立即生效**——无需重启。免重启的每核 CO 搜索是可能的后续阶段；当前
管线只使用 CurveShaper。

## 为什么是外部 CLI 进程？

内核驱动有生命周期（安装、启动、停止）和严格的提权要求。把它隔离在
一个极小的无状态 CLI 里，GUI 就不必包含驱动生命周期代码，提权边界
清晰明确，Python 侧也能把探测失败当普通子进程错误处理
（`MeasurementError` / `TemperatureError`）。

参见：[README.md](README.md) · [CALIBRATION.md](CALIBRATION.md)
