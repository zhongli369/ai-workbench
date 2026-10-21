# 开源替代决策（oss-slim, 2026-10-20）

原则：**原生能力优先，成熟上游其次，自研最后。** 目标 = 低维护成本、低 token 开销、
高可靠性的 Claude Code 工作环境；不再拥有自己的完整 Agent 框架。

证据基础：候选仓库全部经 TLS 校验直连克隆（Windows 证书库，绕过拦截代理）；
PoC 为 3 配置 × 2 相同任务（实现+测试 / 调试），`claude --print --output-format json`
计量，N=1 只做量级判断，不做统计断言。

## 候选核实结果

| 项目 | 版本（核实方式） | License | Windows | 安装 | 结论 |
|---|---|---|---|---|---|
| obra/superpowers | v7.0.0 @ bb92a77（克隆 HEAD 与 ls-remote 一致） | MIT | ✅ 专门加固（polyglot cmd/bash shim；无 bash 静默降级） | 官方 marketplace `/plugin install superpowers@claude-plugins-official`，或会话级 `--plugin-dir` | **选定主工作流** |
| gsd-build/get-shit-done | 原仓已归档，迁至 open-gsd/gsd-core（README 实锤） | MIT | .js+.sh 混合 hooks 17 个 | npx | 排除：项目迁移重写期 + 重注入模型 |
| Yeachan-Heo/oh-my-claudecode | v5.7.5（plugin.json） | MIT | 依赖 psmux/tmux + 外部 CLI（Gemini/Codex） | **全局** npm i -g（违反"避免全局安装"） | 排除：重型多 Agent 编排，与目标相反 |
| oraios/serena | abb0a0f | **GPL-3.0+** | ✅ (uvx) | MCP server | 按需：原生 2.1.x 已内置 LSP；仅大型代码库检索确有收益时启用 |
| promptfoo/promptfoo | 0.124.1 | MIT | ✅（HEAD 提交即修 Windows Node 24） | npx，独立 CLI | 按需：仅真实 LLM 评测时启用 |

## PoC 计量（相同任务，全部 7/7 pytest 通过）

| 配置 | T1 tokens(in+out) | T1 耗时/轮数 | T2 tokens(in+out) | T2 耗时/轮数 |
|---|---|---|---|---|
| A 自研工作台（CLAUDE.md+30 skills+16 agents） | 122,388+1,580 | 59s/7 | 238,610+4,353 | 136s/13 |
| B 原生裸配置 | 88,023+2,035 | 54s/6 | 215,251+3,412 | 119s/13 |
| C 原生+superpowers（--plugin-dir） | 145,961+2,881 | 115s/9 | **143,460+3,135** | 143s/10 |

读法：微任务三者同质量；A 恒最贵（+11%~+39% vs B）；C 在调试任务最省
（systematic-debugging 收敛轮数 13→10），在琐碎实现任务有流程开销。
superpowers 的价值点在复杂长任务的过程纪律（TDD/计划/验收），且**零行自研维护**。

## 替代决策表

| 自研模块 | 替代品 | 保留/替换/禁用 | 证据 |
|---|---|---|---|
| gate（harness_gate.py + gate.py + gateguard/safety-guard） | 无（原生 permissions 是允许/拒绝名单，不含 enforce 阻断+审计+一次性令牌） | **保留** | R1–R3 安全验收；上游无对应物 |
| 项目隔离协议（PROJECTS.md + CLAUDE.md 多项目协议 + 安全底线） | 无 | **保留（瘦身）** | 薄、零维护；CLAUDE.md 删去任务分级/Agent 调度段 |
| 安装器 tools/workbench.py | 无 | **保留** | 维护"保留集"的必需品 |
| feedback 失败史（failure-oracle/experience-capture） | 无上游对应 | **保留（零增长，fail-triggered）** | 存储已在；不再扩张 |
| 16 个专家 agents | 原生 Task + `--agents` + superpowers 编排 skills | **禁用大部分**；security-reviewer 可留 | PoC C 组；原生 `--agents` 二进制确认 |
| 30 个自研 skills（tdd-workflow/plan-orchestrate/deep-research/prompt-optimizer/iterative-retrieval/parallel-execution-optimizer/rules-distill/hookify-rules/context-budget/cost-tracking/memo-* 等） | superpowers 15 skills（TDD/systematic-debugging/writing-plans/executing-plans/verification-before-completion/code-review/worktrees/parallel-agents） | **禁用重复项**（见下"禁用清单"） | superpowers v7.0.0 实机注册 15/15 |
| DEEP 规划与状态（harness plan/checkpoint/verify 日常使用） | 原生 plan mode + `--resume/--continue/--fork-session` + 原生 auto-memory + superpowers writing-plans/executing-plans | **禁用日常使用**；代码保留，需要机械验收门时按需调 | 原生功能二进制确认（2.1.304） |
| 统计（session_metrics hook + telemetry + cost-tracking/report） | 原生 `/cost` `/usage` + OTel 导出 + ccusage（npx 读 transcript） | **保留 hook**（R5 最终裁决：session_id / human_msgs 逐会话台账 `/cost` 不覆盖，实测零维护成本）；cost-tracking skill 禁用 | 原生覆盖大部分；hook 保留接线 |
| 上下文检索（repo-scan/codebase-onboarding/iterative-retrieval） | 原生 Explore agent + 原生 LSP（2.1.x 内置）；大型库再 serena | **禁用**；serena 按需 | `--bare` help 实锤原生 LSP |
| 评测（tools/bench 确定性 20 断言 + eval-harness/benchmark skills） | LLM 评测 → promptfoo（按需 npx）；确定性 bench 无替代需求 | **bench 保留**，eval skills 禁用 | promptfoo MIT/0.124.1 |
| harness-bench-run（独立付费项目） | — | **不动** | 边界约定 |

## 接入方式（极薄适配层，已实现）

启动器新增可选环境变量 `WORKBENCH_PLUGIN_DIR`（tools/workbench.py 的
SH/PS1 模板，默认关闭）：

```bash
# 一次性准备（用户手动，pin commit）：
git clone https://github.com/obra/superpowers %USERPROFILE%\.cache\wb-plugins\superpowers
git -C %USERPROFILE%\.cache\wb-plugins\superpowers checkout bb92a77   # v7.0.0
# 日常使用（需要时）：
set WORKBENCH_PLUGIN_DIR=%USERPROFILE%\.cache\wb-plugins   # 每个子目录 = 一个插件
launch\workbench.sh   # 或 .ps1 —— 启动器自动加 --plugin-dir
```

- 会话级加载，零全局安装，零对生产 settings 的修改。
- 更新方法：`git -C <clone> fetch --tags && git checkout <新 tag>`，先看 CHANGELOG。
- **回滚 = 删掉/清空该环境变量**；rc 侧回滚 = revert 本分支提交。

## 禁用清单（第二阶段，需用户批准后执行；一律 mv 不删除）

runtime 侧（先快照 `snap save`）：
- `.claude/skills/` 移入 `.claude/skills.disabled/`：tdd-workflow, plan-orchestrate,
  deep-research, prompt-optimizer, iterative-retrieval, parallel-execution-optimizer,
  rules-distill, hookify-rules, context-budget, cost-tracking, repo-scan,
  codebase-onboarding, search-first, continuous-learning-v2, benchmark, eval-harness,
  git-workflow, github-ops, frontend-patterns（无前端任务时）
- 保留：gateguard, safety-guard, failure-oracle, experience-capture, workbench,
  ecc-guide, python-patterns, python-testing, error-handling, coding-standards,
  security-review（上游无安全专项）
- `.claude/agents/` 同法：保留 security-reviewer；其余移入 agents.disabled/
- settings.json：~~移除 SessionEnd→session_metrics 条目~~ **已撤销** —— R5 最终裁决保留该 hook（理由见上"替代决策表"统计行）
- CLAUDE.md：删除任务分级/Agent 调度/失败史触发细则段，保留安全底线+多项目协议

## 未实测标记

- 原生 OTel 导出（`CLAUDE_CODE_ENABLE_TELEMETRY` 等）：文档已知，本机未接 collector 实测。
- open-gsd/gsd-core 新仓：网络受限未完成克隆；原仓归档+迁移期已足以排除。
- superpowers 在交互会话的 SessionStart 注入（~800 tok）：`--print` 下未见注入，
  交互模式以实测为准（设计上不影响决策）。

## R7 增补（2026-10-20）：轻量接入核查八点与现行集成清单

### 核查八点（任何新开源能力接入前逐项过；不满足即阻塞，不绕过）

1. **上游来源**：官方/原作者仓；TLS 校验直连克隆，镜像只作下载加速不作信任根。
2. **版本固定**：pin commit/tag（不用分支头），记录核实方式（ls-remote 比对）。
3. **许可证核查**：MIT / Apache-2.0 / BSD 可 vendor；GPL 系只按需外部调用，不 vendor。
4. **Windows 兼容**：实机验证无 bash 环境下启动器与 hooks 行为（静默降级可接受，报错阻塞不可）。
5. **按需加载**：一律会话级 `WORKBENCH_PLUGIN_DIR` + `--plugin-dir`；LEAN 默认不加载可选插件；不写用户级 settings。
6. **Token 与启动开销**：接入前后各跑一次 `--output-format stream-json --verbose` init 探针，记录插件清单与注入规模。
7. **回滚**：会话级 = 清环境变量；vendor 级 = 删目录；rc 级 = revert 提交。回滚不得需要额外工具。
8. **作用域**：LEAN（默认）/ POWER / 仅业务项目会话，三选一并记录；默认"仅业务项目会话"。

### 现行集成（探针实证 2026-10-20）

| 插件 | 上游 | Pin | License | 加载方式 | 作用域 |
|---|---|---|---|---|---|
| superpowers | obra/superpowers | v7.0.0 @ bb92a77 | MIT | POWER 启动器置 `WORKBENCH_PLUGIN_DIR` 指向插件目录本身 | POWER |
| frontend-design | anthropics/claude-plugins-official | a0b04d9 | Apache-2.0 | 用户显式设 `WORKBENCH_PLUGIN_DIR` 后在业务项目目录启动 | 仅业务项目会话 |

实证方法：`--print --output-format stream-json --verbose` 单轮探针，读 init 事件
plugins 清单。当日结果：LEAN = 仅内置插件；POWER = superpowers + 内置；
显式会话 = frontend-design + 内置。

### R7 边界事件与修复（防再犯记录）

- **事件**：frontend-design vendored 在 `vendor/plugins/` 后，POWER 会话同时加载了
  superpowers 与 frontend-design（stream-json init 探针实测发现，代码声明层面不可见）。
- **根因**：`--plugin-dir` 指向父目录时 claude 加载其**每个子目录**；
  POWER 启动器恰好把 `WORKBENCH_PLUGIN_DIR` 设成了 `vendor/plugins` 父目录。
- **修复**：tools/workbench.py 的 POWER_PS1_TMPL / POWER_SH_TMPL 改为指向
  `vendor/plugins/superpowers` 目录本身（探针路径同步改为该目录下的
  `.claude-plugin/plugin.json`）；经安装器重部署 runtime 后三探针复测通过。
- **教训**：凡承诺"只加载 X"的启动器，`--plugin-dir` 必须指向 X 的目录本身，
  不得指向任何父目录。

## R7.2 增补（2026-10-20）：MCP Inspector = 外部 / 按需 / 已验证

- **定位**：外部按需 MCP 调试 CLI。**不**装入工作台、**不**注册为默认 MCP、
  **不**改动 LEAN/POWER 启动器、零行 Harness 代码、零常驻进程。
- **上游与版本**：官方 `modelcontextprotocol/inspector`，
  `@modelcontextprotocol/inspector@2.11.0`（npm 镜像可解析，TLS 校验未关）。
- **PoC 证据**（`%TEMP%` 隔离目录 + 隔离 npm cache 安装；官方示例服务器
  `@modelcontextprotocol/server-everything@2.0.0`；全程无模型 API 调用）：
  - `tools/list`：17 个工具，exit 0（冷启动约 0.6s）。
  - `tools/call get-sum a=2 b=3`：真实返回 **5**，exit 0（约 0.7s）——
    不是仅凭工具列表判成功。
  - 故障分级实测：连接失败 exit 1（"Connection closed" + 被孵进程 stderr
    透传）；工具/参数错误 exit 5（tool_not_found / validation 的结构化 JSON）。
  - 零残留：不创建 `~/.mcp-inspector`，不写用户级配置；PoC 目录已清理。
- **用法**（真实命令，在需要调试的业务项目内执行）：

  ```powershell
  # 偶发尝鲜：npx 直调（温缓存下仍约 86s，不适合日常）
  npx --yes @modelcontextprotocol/inspector@2.11.0 --cli node <server.js> --method tools/list

  # 推荐：项目内本地安装后直调（约 0.7s；node_modules 约 86MB）
  npm install --save-dev @modelcontextprotocol/inspector@2.11.0
  node_modules\.bin\mcp-inspector --cli node <server.js> --method tools/list
  node_modules\.bin\mcp-inspector --cli node <server.js> --method tools/call --tool-name get-sum --tool-arg a=2 --tool-arg b=3
  ```

- **已知边界**：`--catalog` 与 ad-hoc 命令不兼容；`-e` 是 inspector 自身的
  环境变量旗标（给被测服务器传代码请用脚本文件，不要用 `node -e` 内联）。

## 候选状态总表（2026-10-21 收官登记）

| 候选 | 状态 | 依据 |
|---|---|---|
| Superpowers v7.0.0 @bb92a77 | **Active / On-demand**（POWER 启动器） | PoC 计量 + 三轮 stream-json 探针（上文） |
| frontend-design @a0b04d9 | **Verified / Explicit**（会话级显式启用） | 探针实证；R7 边界事件修复后复测通过 |
| MCP Inspector 2.11.0 | **External / On-demand / Verified** | R7.2 PoC（上文） |
| Playwright MCP | **Deferred** | registry 登记为 off；无真实浏览器自动化需求 |
| Context7 | **Deferred** | 未评测；无真实文档检索需求 |
| Promptfoo | **Deferred** | 无 LLM 评测需求与预算 |
| Beads | **Rejected** | 用户裁决登记，未做评测 |
| Spec Kit | **Rejected** | 用户裁决登记，未做评测 |
| Claude Code Action | **N/A** | 无 CI 内自动会话场景，用户裁决登记 |

状态含义：**Active** = 现行集成；**Verified** = 技术可行性已实证；
**Explicit** = 仅用户显式启用；**External** = 不进入工作台本体；
**Deferred** = 出现真实需求时按核查八点重评；**Rejected** = 不采用；
**N/A** = 场景不适用。
