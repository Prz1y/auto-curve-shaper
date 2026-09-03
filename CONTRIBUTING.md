# Contributing to Auto Curve Shaper

感谢你对 Auto Curve Shaper 的兴趣！我们欢迎各种形式的贡献。

## 贡献方式

### 🐛 报告 Bug

在提交 Bug 之前，请：
1. 检查是否已有相关 Issue
2. 确认使用的是最新版本
3. 收集必要信息：
   - CPU 型号
   - Windows 版本
   - Python 版本
   - 错误日志（`logs/` 目录）
   - `state.json`（如果相关）

提交 Issue 时包含：
- 清晰的标题
- 重现步骤
- 预期行为 vs 实际行为
- 相关日志和截图

### 💡 功能建议

我们欢迎新功能建议！请：
1. 检查是否已有相关建议
2. 描述使用场景和预期收益
3. 考虑实现难度和维护成本

### 📝 改进文档

文档改进总是受欢迎的：
- 修正错误
- 添加示例
- 改进说明
- 翻译（目前支持中英文）

### 🔧 提交代码

#### 准备工作

1. Fork 仓库
2. 创建功能分支：
   ```bash
   git checkout -b feature/your-feature-name
   ```

#### 代码规范

- **Python 风格**：遵循 PEP 8
- **命名**：
  - 函数/变量：`snake_case`
  - 类：`PascalCase`
  - 常量：`UPPER_CASE`
- **文档字符串**：所有公共函数需要 docstring
- **类型注解**：对公共 API 使用类型注解
- **注释**：解释"为什么"，而不是"做什么"

#### 示例代码

```python
def measure_frequency(duration: int, workload: str = "idle") -> FrequencyMeasurement:
    """
    Measure CPU frequency under specified workload.
    
    Args:
        duration: Measurement duration in seconds
        workload: "idle" or "load"
    
    Returns:
        FrequencyMeasurement with per-core frequencies
    
    Raises:
        ValueError: If duration <= 0
        RuntimeError: If measurement fails
    """
    if duration <= 0:
        raise ValueError("Duration must be positive")
    
    # Implementation...
```

#### 提交信息

使用清晰的提交信息：

```
类型: 简短描述（50 字符以内）

详细描述（如果需要），解释：
- 为什么需要这个改动
- 如何解决问题
- 有什么副作用或注意事项

Fixes #123
```

**类型**：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档
- `style`: 格式（不影响代码逻辑）
- `refactor`: 重构
- `test`: 测试
- `chore`: 构建/工具

#### Pull Request

1. 确保代码通过所有测试
2. 更新相关文档
3. 在 PR 中描述：
   - 改动内容
   - 测试方法
   - 截图（如果是 UI 改动）
4. 关联相关 Issue

## 开发环境设置

### 克隆仓库

```bash
git clone https://github.com/YOUR_USERNAME/auto-curve-shaper.git
cd auto-curve-shaper
```

### 安装依赖

项目只依赖 Python 标准库，无需额外安装。

### 运行测试

```bash
# 单元测试（待添加）
python -m pytest tests/

# 手动测试
python main.py  # CLI
python gui.py   # GUI
```

### 代码检查

```bash
# 格式检查
flake8 *.py

# 类型检查
mypy *.py
```

## 项目结构

```
auto-curve-shaper/
├── main.py              # CLI 入口
├── gui.py               # GUI 入口
├── optimizer.py         # 优化引擎
├── state_manager.py     # 状态管理
├── frequency_monitor.py # 频率监测
├── utils.py             # 工具函数
├── config.py            # 配置
├── tests/               # 测试（待添加）
├── docs/                # 文档
└── examples/            # 示例
```

## 优先开发任务

### 高优先级
- [ ] 单元测试套件
- [ ] CI/CD 管道
- [ ] 自动重启支持
- [ ] 更好的错误恢复
- [ ] 性能优化（减少测试时间）

### 中优先级
- [ ] 多 CPU 支持（验证其他 Zen 5 型号）
- [ ] 导出/导入配置
- [ ] 结果可视化图表
- [ ] Web UI（可选）
- [ ] 远程监控

### 低优先级
- [ ] 其他优化目标（功耗、效率）
- [ ] 机器学习预测
- [ ] 多语言支持
- [ ] Docker 容器化

## 测试指南

### 手动测试清单

测试新功能前：
- [ ] 备份 `state.json`
- [ ] 记录当前 CurveShaper 设置
- [ ] 准备恢复方案

测试步骤：
1. 基础功能：启动、配置、日志
2. 状态管理：保存、恢复、重置
3. 优化流程：基线、单元格优化、完成
4. 错误处理：无效输入、权限错误、崩溃恢复
5. GUI：所有按钮、显示更新、响应性

### 自动化测试（待实现）

```python
# tests/test_state_manager.py
def test_state_persistence():
    state = OptimizationState()
    state.iteration = 5
    state.save()
    
    loaded = OptimizationState.load()
    assert loaded.iteration == 5
```

## 安全考虑

提交代码时注意：
- **不要**硬编码敏感信息
- **不要**包含个人数据（CPU 序列号等）
- **验证**用户输入
- **限制**资源使用（防止 DOS）
- **记录**安全相关操作

## 发布流程

1. 更新版本号（`config.py`）
2. 更新 CHANGELOG.md
3. 运行完整测试
4. 创建 Git tag
5. 发布 GitHub Release
6. 更新文档

## 社区行为准则

- 尊重所有贡献者
- 欢迎新手问题
- 建设性反馈
- 专注于技术讨论
- 遵守开源协议

## 获得帮助

- 📖 阅读 [README.md](README.md) 和 [QUICKSTART.md](QUICKSTART.md)
- 💬 在 Issues 中提问
- 📧 联系维护者

## 致谢

贡献者将被添加到 README.md 的致谢部分。

---

感谢你的贡献！🎉
