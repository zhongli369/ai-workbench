# AI Workbench

*Claude Code 的轻量通用增强环境 — 最小默认干扰、必要安全保障、成熟插件按需接入、可靠安装与回滚。*

`v0.1.0-preview.5` · **Stable / Maintenance Mode**（维护模式，见 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)）· [English](README.md)

| 徽章 | 状态 |
|---|---|
| CI（契约 + 静态检查 + CLI 冒烟） | [![ci](https://github.com/zhongli369/ai-workbench/actions/workflows/ci.yml/badge.svg)](https://github.com/zhongli369/ai-workbench/actions/workflows/ci.yml) |
| 供应链安全扫描 | [![security](https://github.com/zhongli369/ai-workbench/actions/workflows/security.yml/badge.svg)](https://github.com/zhongli369/ai-workbench/actions/workflows/security.yml) |
| License | [![license](https://img.shields.io/github/license/zhongli369/ai-workbench)](LICENSE) |

---

## 1. 项目定位（是什么 / 不是什么）

AI Workbench 是 Claude Code 的轻量通用增强环境：一次安装的工作台层，
从一个会话操作多个项目，提供安全门控、按需能力与可回滚的安装。

它**不是**：

- 独立大模型
- 第二套 Agent 框架
- Java / Python 全栈业务系统
- 多 Agent 全自动调度平台
- 强制规划与验证的重型 Harness

设计目标：**最小默认干扰、必要安全保障、成熟插件按需接入、可靠安装与回滚。**

历史依据：harness-bench 对照实测证明重型默认注入**降低**任务表现
（SE 家族 -0.486），因此默认保持轻量（LEAN），重型能力一律按需。

## 2. 当前功能

### 默认启用（LEAN 模式）

| 能力 | 机制 |
|---|---|
| LEAN 会话策略 | `workbench/CLAUDE.md`（83 行，随安装进入工作台根） |
| 三层不可逆命令 Gate | 单一 `PreToolUse` hook（Bash + PowerShell）；生产默认 **audit** |
| SessionEnd Metrics | `hooks/session_metrics.py` → `harness-data/session-metrics.jsonl`（计数型，不含会话内容） |
| 多项目工作协议 | `PROJECTS.md` 速查表 + 绝对路径 / `git -C`；目标项目 `CLAUDE.md` 经 `/add-dir` 按需加载 |
| MCP 默认 0 | 启动器强制 `--strict-mcp-config` |
| 按需能力子集 | **11 skills** / **1 agent** / 14 commands（**(11+1+14)**，按任务加载，pin 见 `vendor/ecc/`） |
| 全局规则豁免 | `claudeMdExcludes` 防止全局规则包遮蔽目标项目自身规则 |

### 显式按需启用

| 能力 | 启用方式 |
|---|---|
| POWER 模式（Superpowers v7.0.0 @bb92a77，固定版） | `launch\workbench-power.ps1` — 仅加载 superpowers，不叠加同级插件 |
| frontend-design @a0b04d9（Apache-2.0） | 会话级 `WORKBENCH_PLUGIN_DIR` 显式指定（见快速开始） |
| harness CLI：`plan` / `checkpoint` / `verify` / `snap` / `feedback` / `gate` / `telemetry` | 显式调用，非常驻流程 |
| MCP Inspector 2.11.0（MCP 调试） | 外部 CLI，`npx` 直调；不注入工作台、不注册为 MCP |
| capability 注册中心（16 项） | `workbench capability list/enable/disable`；外部能力**从不自动安装** |

### 已禁用（保留未删，可 `git mv` 恢复）

19 个 skills 与 15 个 agents 位于 `workbench/disabled/`（安装后对应
`.claude/skills.disabled` / `agents.disabled`）——与上游成熟能力重复的
自研职能，R5 瘦身时移出，**不是**默认活跃能力。

## 3. 快速开始（Windows PowerShell，全部实测）

要求：Python ≥ 3.10 + Claude Code CLI。harness-core 为纯 stdlib
（纯 stdlib, 253 项契约），无需 pip 安装。

下列命令安装到默认位置；自定义安装目录用全局参数 `--target <目录>`
（放在子命令**之前**）——下文 `<目标目录>` 即安装根目录。

```powershell
# 1. 安装（幂等、可 dry-run，只写目标目录）
git clone https://github.com/zhongli369/ai-workbench.git
cd ai-workbench
python tools/workbench.py doctor
python tools/workbench.py install --yes

# 2. LEAN 启动（默认）
<目标目录>\launch\workbench.ps1

#    等价：打印并执行确切启动命令
python tools/workbench.py launch --run

# 3. POWER 启动（LEAN + Superpowers）
<目标目录>\launch\workbench-power.ps1

# 4. 显式启用 frontend-design（会话级，建议在某业务项目目录内启动）
$env:WORKBENCH_PLUGIN_DIR = "<目标目录>\vendor\plugins\frontend-design"
<目标目录>\launch\workbench.ps1

# 5. 用完清除会话级配置（零全局状态）
Remove-Item Env:WORKBENCH_PLUGIN_DIR

# 6. 查看当前 Gate 模式（生产默认 audit）
python <目标目录>\harness-core\harness\cli.py gate check "git push origin main"
#    输出: {"decision": "audit", "mode": "audit", ...}

# 7. 按需 verify（机械验收门）
python <目标目录>\harness-core\harness\cli.py verify status --exec <id>

# 8. 查看版本 / 安装状态
python tools/workbench.py status

# MCP 调试（外部按需 CLI，不装入工作台）
npx --yes @modelcontextprotocol/inspector@2.11.0 --cli node <server.js> --method tools/list
```

卸载只删除 manifest 登记的受管文件，用户数据默认保留
（追加 `--purge-data` 才清除）：

```powershell
python tools/workbench.py uninstall --yes
```

## 4. 使用建议

- **简单任务用 LEAN**（默认）：直接执行，不规划、不起 agent。
- **复杂调试 / TDD / 系统性开发用 POWER**：Superpowers 提供过程纪律；
  不要给简单任务套 POWER 流程，也不要宣称 POWER 一定优于 LEAN。
- **设计界面时**显式启用 frontend-design。
- **MCP 调试**用外部 Inspector CLI。
- 其他专业工具（Playwright MCP / Context7 / Promptfoo）需要时再引入，
  状态与核查规范见 [docs/open-source-adoption.md](docs/open-source-adoption.md)。

## 5. 目录结构（源码仓）

```
ai-workbench/
├─ tools/workbench.py      ← 安装器 / CLI（doctor install launch status capability uninstall）
├─ workbench/              ← 安装载荷源：CLAUDE.md、.claude/（11+1+14）、disabled/（19+15）
├─ harness-core/           ← 纯 stdlib CLI 工具包（253 契约，可独立使用）
├─ hooks/                  ← harness_gate.py（gate）+ session_metrics.py（SessionEnd）
├─ capabilities/           ← 能力注册中心（registry.json + wiring）
├─ vendor/                 ← 第三方固定版快照（ecc 溯源 stub、plugins）
├─ tests/                  ← 仓级契约（含 battle / multiproj）
└─ docs/                   ← MAINTENANCE.md、open-source-adoption.md、claims/surface 门禁
```

安装产物（`--target` 目录）额外包含：`launch/`（LEAN/POWER 启动器）、
`harness-data/`（gate.json、session-metrics.jsonl 等用户数据）、
`install-manifest.json`（受管文件清单 + sha256 漂移保护）。

## 6. 安全和边界

- **Gate 三模式**：`disabled` 不干预；`audit` 记录并提示（**可观测性，不是防护**）；
  `enforce` 拦截配置的高危模式（push / reset --hard / rm -rf / publish / deploy），
  需一次性令牌（`gate approve --once`）预授权。当前生产默认 **audit**。
- **Gate ≠ 模型绝对安全保证**；`claude --print` 非交互模式不执行 `PreToolUse`
  hooks（CC 2.1.x 实测），enforce 只对交互会话生效。
- **不允许绕过用户授权**；Gate 模式不能由模型擅自更改。
- **各业务项目应独立 Git 仓库**；Workbench 不承载业务代码、依赖、测试或项目专属配置。
- **受管文件 vs 用户数据边界**：`PROJECTS.md` / `settings.json` / `gate.json`
  永不覆盖；其余受管文件由 manifest 逐文件 sha256 保护——本地修改过的受管文件
  重装时先备份为 `<file>.user-bak` 再刷新为 canonical。
- **全局 `~/.claude/CLAUDE.md` 是用户个人配置**，安装器从不读取或修改。

## 7. 维护状态

**Stable / Maintenance Mode。** 仅允许四类修改：真实安全缺陷、Claude Code
上游兼容性失效、已确认的功能故障、多个真实项目反复出现且原生与成熟插件
无法解决的通用能力缺口。详见 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。

- 当前版本 `0.1.0-preview.5`（未打 Release；最新已发布 Release 仍为
  `v0.1.0-preview.3`）。
- R6 极简候选 `r6-slim @1b91f1c`：**独立实验候选，未证明净收益，未合并、
  未部署、默认不启用。**

## 8. 证据

- **540 项离线契约** = **253 harness-core**（确定性, 253 项契约）
  + **287 tests**；该数字由 `tools/check_docs_drift.py` 对照 pytest 收集
  结果实时校验，本 README 不得与之偏离。
- CI（[.github/workflows/ci.yml](.github/workflows/ci.yml)）：三 OS ×
  Python 3.10–3.12 + 静态门禁（hygiene / docs-drift / public surface）。
- 插件隔离实证（2026-10-20，stream-json init 探针）：LEAN 仅内置插件；
  POWER = superpowers；显式会话 = frontend-design。
- 复现演示：[docs/demos.md](docs/demos.md)。

## 9. 相关文档

[English README](README.md) · [docs/MAINTENANCE.md](docs/MAINTENANCE.md)
（维护模式）· [docs/open-source-adoption.md](docs/open-source-adoption.md)
（开源能力接入与状态）· [CHANGELOG.md](CHANGELOG.md) ·
[harness-core/README.md](harness-core/README.md) ·
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [SECURITY.md](SECURITY.md) ·
[NOTICE](NOTICE)（第三方署名）· [CONTRIBUTING.md](CONTRIBUTING.md)

## License

本分发自有代码采用 MIT。everything-claude-code 由其作者以 MIT 发布——
见 `vendor/ecc/LICENSE` 与 [NOTICE](NOTICE)。
