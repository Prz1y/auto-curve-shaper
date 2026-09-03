# GitHub 仓库创建指南

由于系统中未安装 Git，请按照以下步骤手动创建 GitHub 仓库。

## 步骤 1: 安装 Git

### 选项 A: 使用 Git for Windows
1. 下载：https://git-scm.com/download/win
2. 运行安装程序，使用默认设置
3. 重启命令行窗口

### 选项 B: 使用 Winget
```powershell
winget install Git.Git
```

## 步骤 2: 配置 Git（首次使用）

```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

## 步骤 3: 初始化本地仓库

在项目目录中运行：

```bash
cd C:\Users\deepi\Documents\auto-curve-shaper
git init
git add .
git commit -m "Initial commit: Auto Curve Shaper for AMD Zen 5"
```

## 步骤 4: 在 GitHub 上创建仓库

### 选项 A: 使用 GitHub CLI（推荐）

1. 安装 GitHub CLI：https://cli.github.com/
2. 登录：
   ```bash
   gh auth login
   ```
3. 创建仓库并推送：
   ```bash
   gh repo create auto-curve-shaper --public --source=. --remote=origin --push
   ```

### 选项 B: 手动创建

1. 访问 https://github.com/new
2. 填写仓库信息：
   - Repository name: `auto-curve-shaper`
   - Description: `Automatic AMD Zen 5 CurveShaper voltage curve optimizer for maximum CPU frequency`
   - Public/Private: 选择 Public
   - **不要**初始化 README、.gitignore 或 license（我们已经有了）
3. 点击 "Create repository"
4. 在本地仓库中添加远程地址并推送：
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/auto-curve-shaper.git
   git branch -M main
   git push -u origin main
   ```

## 步骤 5: 添加仓库描述和标签

在 GitHub 仓库页面：

1. 点击设置图标（齿轮）
2. 添加描述：
   ```
   Automatic AMD Zen 5 CurveShaper voltage curve optimizer for maximum CPU frequency
   ```
3. 添加标签（Topics）：
   - `amd`
   - `zen5`
   - `ryzen`
   - `overclocking`
   - `optimization`
   - `voltage-curve`
   - `curveshaper`
   - `python`

## 推荐的仓库设置

### About 部分
- Website: 留空或添加你的博客
- Topics: 如上所示

### README.md
已包含完整文档，包括：
- 功能概述
- 安装说明
- 使用指南
- 技术细节
- 安全警告

### 保护 main 分支（可选）
Settings → Branches → Add branch protection rule:
- Branch name pattern: `main`
- Require pull request reviews before merging
- Require status checks to pass before merging

## 后续推送

在进行更改后：

```bash
git add .
git commit -m "描述你的更改"
git push
```

## 快速命令参考

```bash
# 查看状态
git status

# 查看更改
git diff

# 添加文件
git add <file>
git add .  # 添加所有更改

# 提交
git commit -m "提交信息"

# 推送到 GitHub
git push

# 拉取更新
git pull

# 查看历史
git log --oneline
```

## 故障排除

### 问题：推送时要求输入用户名/密码
使用 Personal Access Token (PAT)：
1. GitHub → Settings → Developer settings → Personal access tokens → Generate new token
2. 选择 `repo` 权限
3. 使用 token 作为密码

### 问题：推送被拒绝
```bash
git pull --rebase origin main
git push
```

---

完成后，你的仓库将位于：
https://github.com/YOUR_USERNAME/auto-curve-shaper
