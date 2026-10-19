# AGENTS.md — AI Workbench 仓库入口（Codex）

本文件是 Codex 在本仓库的开发入口。Claude Code 的入口是同目录
`CLAUDE.md`；双方共享的协作规则在 `docs/AI_COLLABORATION.md`。
安装后的工作台会话策略是 `workbench/CLAUDE.md`（产品载荷），不是本仓库的
开发规则，二者不要混用。

## 项目定位

AI Workbench 是面向 Claude Code 的轻量、可治理、按需加载的工程工作台：

- 一个工作台会话操作多个项目，用绝对路径 / `git -C` 明确目标；
- 专家能力按任务加载，不默认常驻；
- 不可逆命令经过三层 gate（DISABLED / AUDIT / ENFORCE）；
- `harness-core` 提供失败记忆、检查点、验证、快照与 gate，纯标准库实现。

事实来源以实际代码和实时命令为准：

- 版本：`tools/workbench.py` 的 `VERSION`（当前开发版为 `0.1.0-preview.5`；
  README 中的发布链接可能仍指向最近已发布的 `0.1.0-preview.3`）。
- 能力清单：`capabilities/registry.json`（当前 16 项，含默认关闭的按需能力）。
- 契约数量：以 `python -m pytest ...` 的实际收集/通过数为准，不把 README
  中的历史数字当作当前证据。
- Git 状态：以 `git log -1`、`git status`、`git rev-parse HEAD` 为准。

## 代码地图

| 路径 | 作用 |
|---|---|
| `tools/workbench.py` | 安装器 CLI：doctor / install / launch / status / capability / uninstall / benchmark |
| `tools/` | 文档漂移、公共表面、卫生、技能质量、安全扫描等门禁脚本 |
| `harness-core/harness/` | 纯标准库核心：feedback / gate / telemetry / checkpoint / plan / verify / snap |
| `harness-core/tests/` | harness-core 契约测试 |
| `tests/` | 安装、能力、文档、安全、技能等仓库级契约测试 |
| `hooks/harness_gate.py` | 唯一的 PreToolUse gate 钩子 |
| `workbench/` | 安装后的工作台载荷：`CLAUDE.md`、`.claude/` 技能/代理/命令、启动模板 |
| `capabilities/` | 能力注册表与按需接线模板（`registry.json`、`wiring/`） |
| `vendor/ecc/` | 固定版本的 ECC 上游快照（MIT，见 `NOTICE`） |
| `docs/` | 架构、能力证据、决策记录、公共表面与发布检查 |
| `experiments/` | 隔离原型，不进入默认安装载荷 |
| `examples/`、`tools/bench/` | 示例与基准任务，不是运行时核心 |
| `.github/workflows/` | CI 契约矩阵与 supply-chain 安全门 |

## 开发与验证命令

环境要求：Python ≥ 3.10；`harness-core/`、`tools/`、`hooks/` 不新增运行时
依赖。测试需要 `pytest`。无构建步骤；CI 会用 `zipapp` 打包安装器。

```powershell
# 环境预检（只读，不写入）
python tools/workbench.py doctor

# 契约测试（按风险选择，提交前至少跑受影响范围；完整门禁跑前两条）
python -m pytest harness-core/tests/ -q
python -m pytest tests/ -q
python -m pytest harness-core/tests/ tests/ -q

# 静态门禁（与 .github/workflows/ci.yml 一致）
python -m compileall -q tools/ harness-core/harness/ hooks/
python tools/check_hygiene.py
python tools/check_docs_drift.py
python tools/check_public_surface.py
python tools/check_skills.py --root .

# 本地许可证清单（不需要 trivy；完整 supply-chain 扫描在 CI 中执行）
python tools/security_scan.py . --licenses
```

完整 supply-chain 门依赖 `trivy` 和网络；本地缺少工具或漏洞库时，记录
`BLOCKED` / `UNVERIFIED`，不得当成 PASS。Windows 下优先用 `python`，含空格
的路径必须加引号；提交前确保文件为 UTF-8。

## Codex 职责

Codex 可以独立承担：功能开发、Bug 修复、单元/集成测试、架构评估、性能优化、
安全审查、文档更新，以及对 Claude Code 提交的独立审查。Codex 不是只读
Review 工具，也不要求所有实现都等待 Claude Code。

## 边界与禁止

- 不覆盖 Claude Code 或其他开发者未提交的修改；开始前先看 `git status`。
- 不修改用户全局配置（仓库外的 `CLAUDE.md`、Claude/Codex 配置、全局 hooks）。
- 不重写 Git 历史；不 `git reset --hard`、不 `git clean -fd`、不 force push。
- 不跳过 Gate / Verify / Security；不把未验证结果报告为 PASS。
- 不访问无关项目；不自动部署或发布；不擅自合并到 `main`。
- 不未经允许调用额外付费外部服务，不把私有代码发送到未授权的模型 Provider。
- 不新增无价值依赖、后台服务、Agent 调度框架或重复的规划系统。
- 不在入库文件中写机器绝对路径、密钥形状或用户私有路径。

## 双引擎工作方式

- Codex 默认使用 `codex/<topic>` 分支；Claude Code 默认使用
  `claude/<topic>` 分支。并发开发时各自使用独立 worktree，不同 worktree
  必须挂不同分支。
- 同一个 Git 工作区同一时间只允许一个模型写入。若必须改同一模块，先完成
  并提交一方的工作，另一方基于最新提交继续。
- 提交前写明 `BASE SHA`、实际测试命令和结果；交接格式见
  `docs/AI_COLLABORATION.md`。
- 交叉 Review 是按需能力，不是每个任务的强制步骤；涉及共享文件、安全核心
  或高风险改动时应执行。

## 环境备注

PATH 上的 `codex` 可能是同名 npm 工具（`0.2.3`，静态站生成器），不是 OpenAI
Codex CLI。真正的 CLI 应报告 `codex-cli <version>`；调用审查自动化前先确认
版本前缀，避免把错误工具当成 Codex。
