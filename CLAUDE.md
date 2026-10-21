# AI Workbench — 仓库开发入口（Claude Code）

本文件是 Claude Code 在本仓库的开发入口。产品安装后的工作台会话策略是
`workbench/CLAUDE.md`，它不是本仓库的开发规则；不要用安装载荷替代本文件。

## 项目

AI Workbench 是面向 Claude Code 的轻量、可治理、按需加载的工程工作台：
一个工作台操作多个项目，能力按任务加载，不可逆命令经过三层 gate。
当前版本以 `tools/workbench.py` 的 `VERSION` 为准；能力清单以
`capabilities/registry.json` 为准。本仓库处于维护模式，仅四类修改允许
（见 `docs/MAINTENANCE.md`）。

## 必读

1. `docs/AI_COLLABORATION.md`：Codex × Claude Code 共享协作协议。
2. `AGENTS.md`：Codex 入口、代码地图、验证命令和边界。
3. `CONTRIBUTING.md`、`SECURITY.md`、`docs/ARCHITECTURE.md`：原有开发与
   安全规则，继续有效。

## 双引擎协作

- Codex 与本项目平等，都是独立的开发执行器；Claude Code 不是唯一实现者。
- Claude Code 默认使用 `claude/<topic>` 分支；并发开发时使用独立 worktree。
- 不要在同一工作区同时编辑 Codex 正在修改的文件；开始前先看 `git status`。
- 不要覆盖 Codex 未合并的成果；共享文件或高风险改动按需交叉 Review。
- 共享规则、文件所有权、交接格式和冲突解决见
  `docs/AI_COLLABORATION.md`，不要在本文件复制整段规则。

## 验证

提交前至少运行与改动相关的契约；完整门禁与 CI 一致：

```powershell
python -m pytest harness-core/tests/ tests/ -q
python -m compileall -q tools/ harness-core/harness/ hooks/
python tools/check_hygiene.py
python tools/check_docs_drift.py
python tools/check_public_surface.py
python tools/check_skills.py --root .
```

环境预检用 `python tools/workbench.py doctor`（只读）。缺少工具、网络或登录
凭据时标记 `BLOCKED` / `UNVERIFIED`，不要把未执行的检查写成 PASS。

## 安全底线

- 不修改用户全局配置、仓库外全局 `CLAUDE.md` 或全局 hooks。
- 不重写 Git 历史，不 force push，不 `git reset --hard`，不 `git clean -fd`。
- 不跳过 Gate / Verify / Security，不自动部署或发布，不擅自合并到 `main`。
