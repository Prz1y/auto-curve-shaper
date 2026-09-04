# 参与贡献 Auto Curve Shaper

感谢你有兴趣为本项目做贡献！本项目基于 **GPL-3.0-or-later** 许可证——
提交贡献即表示你同意以相同条款授权你的成果。

其他语言 / Other language: [English version](../en/CONTRIBUTING.md)

---

## 贡献方式

### 🐛 报告 Bug

提交前请：

1. 搜索已有 Issue
2. 确认使用的是最新版本
3. 收集：CPU 型号、Windows 版本、Python 版本、`logs/` 下的日志，
   相关时附 `state.json`

Issue 请包含清晰的标题、重现步骤、预期与实际行为、关键日志摘录。

### 💡 功能建议

请描述使用场景和预期收益。涉及硬件行为的特性请说明*实测*依据
（频率、WHEA 计数、温度），而不是假设。

### 📝 文档

文档位于 `docs/en/` 和 `docs/zh/`，两个语言版本必须保持同步——改了
一边请镜像另一边（或者注明需要翻译）。

### 🔧 代码

#### 准备工作

```bash
git clone https://github.com/YOUR_USERNAME/auto-curve-shaper.git
cd auto-curve-shaper
# 仅依赖标准库 —— 无需 pip install
```

#### 测试

```bash
python tests\test_derive.py      # 求解器，合成数据
python tests\test_pipeline.py    # 完整管线状态机（模拟硬件）
python -m py_compile *.py        # 语法检查
```

`test_pipeline.py` 不碰硬件——没有探测工具调用、没有重启、不碰真实的
`state.json`（重定向到临时文件）。**已知局限**：模拟抓不到负载集成的
回归。如果你改了 `frequency_monitor` 或 `workload` 的函数签名，请另外
做一次真实短测：提权环境下 `measure_frequencies_load(20)` +
`run_stability_test(10)`。

#### 风格

- PEP 8；函数 `snake_case`、类 `PascalCase`、常量 `UPPER_CASE`
- 公共函数写 docstring；公共 API 加类型注解
- 注释解释"为什么"，而不是"做什么"
- 测量基础设施的失败必须抛异常（`MeasurementError`、
  `TemperatureError`、`WorkloadError`）——绝不能被误判为配置失稳

#### 提交信息与 PR

```
类型: 简短描述（50 字符以内）

为什么需要这个改动、如何解决、有什么副作用。

Fixes #123
```

类型：`feat` `fix` `docs` `style` `refactor` `test` `chore`。

PR 要求：测试通过、文档同步更新、说明改了什么和怎么测的。
涉及硬件行为的改动请注明在哪块 CPU/主板上验证过。

## 项目结构

见完整文档的[项目结构](README.md#项目结构)章节。新模块请保持管线
依赖的分层：`calibration.py`（硬件编排）与 `derive.py`（纯逻辑、可离线
测试）泾渭分明。

## PR 安全红线

- 没有充分且记录在案的理由，不要移除或弱化稳定性门槛、WHEA 监控、
  上限 clamp
- 新的负载机制必须在失败路径上被终止（参考 `workload.LoadHandle` /
  `atexit` 清理）
- 一切 CS 写入必须走重启状态机——运行期写入不生效，只会制造假测试
  结果

## 发布流程

1. 更新 `config.py` 里的 `VERSION` / `RELEASE_DATE`
2. 更新 `CHANGELOG.md`
3. 跑离线测试套件
4. 打 tag 并发布

## 社区行为准则

尊重所有参与者、欢迎新手、聚焦技术讨论。参与即表示同意遵守项目
许可证条款。

---

感谢你的贡献！🎉
