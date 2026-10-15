# 对抗性验收基线 — Agent D (ADVERSARIAL TESTER)

日期：2026-10-15 · 分支：feat/surgical-upgrade（主树，未 commit）· 环境：Windows 11 Pro 10.0.26200，
Python 3.12.6，git 可用，PowerShell RemoteSigned。
方法：以下每条命令均在主树或 `$TMP` 隔离目录真实执行；引号内为真实输出关键行，无任何编造。
临时环境保留在 `$TMP`（`aiwb-*`、`工作台测试`），供后续验收复用。

## 一、FAST 默认开销基线

| 项 | 基线值 | 证据 |
|---|---|---|
| 仓库 `.claude/settings.json` | **不存在**（仓库内 hooks = 0） | `.claude/` 仅含 `worktrees/`；`.gitignore` 未忽略它 |
| install 模板 hooks | PreToolUse ×1（matcher: Bash → `python {{ROOT}}/hooks/harness_gate.py`） | `tools/workbench.py:41-50` SETTINGS_TMPL |
| hooks 分类计数（仓库/模板） | SessionStart 0 · UserPromptSubmit 0 · PreToolUse 1(模板) · PostToolUse 0 · Stop 0 | 同上 |
| 用户级 settings.json hooks（环境对照） | PreCompact×1(claude-baton auto-checkpoint) · SessionStart×1(caveman-activate.js) · UserPromptSubmit×1(caveman-mode-tracker.js) · PreToolUse **0** | 读 `~/.claude/settings.json`；doctor 亦报 "用户级 PreToolUse hooks: 0 个" |
| MCP servers（仓库） | **0**（无 `.mcp.json`；settings 无 `mcpServers`） | 全会话 MCP(codegraph/scrapling/claude-baton/ide) 来自用户配置，非仓库 |
| skills / agents / commands | 30 / 16 / 14 | `find workbench/.claude/skills -name SKILL.md \| wc -l` = 30 |
| 常驻进程（本仓库相关） | **0** | tasklist：python×1=scrapling MCP、node×4=claude-baton/codegraph MCP；命令行均无 ai-workbench 路径 |
| 启动路径网络调用 | **0** | `harness/*.py`、`hooks/*.py` 无 urllib/socket/http 导入；`tools/workbench.py` 仅本地子进程（`claude --version`/`git`/`powershell Get-ExecutionPolicy`）；`project_id.py` 仅本地 `git remote -v` |
| 网络能力脚本（非启动路径） | `tools/release_publish.sh`（curl，人工发布）、`tools/_relay_github.py`（本地 relay，dev-only）、`.github/workflows/*`（仅 CI） | 静态读码 |
| 强制流程要求（只列事实） | `workbench/CLAUDE.md`：安全底线×4（验证才说完成/无硬编码密钥/不可逆命令经 gate/边界校验）· 任务分级 FAST/STANDARD/DEEP/RECOVERY · telemetry CLI 自动记录 · 失败史仅 fail-triggered · 多项目协议×6（绝对路径/`git -C`/PROJECTS.md 不扫盘/未授权只读）· 诚实分级。`F:\Claude\CLAUDE.md`（工作区）：原生执行优先 · plan/checkpoint/snap/verify/gate/feedback **按需不自动注入** · 改后按任务验证 · 退役系统禁引用 | 两文档原文 |

观测：本会话读取 `workbench/` 下文件后，CC 自动发现并列出 30 个 skill（系统提示实测）——即进入
工作台树会触发 skill 索引加载，属 workspace 层开销而非本仓库进程开销。

**结论：PASS（基线已记录，数字可复核）。**

## 二、核心契约套件回归

| 命令 | 真实输出关键行 | 退出码 |
|---|---|---|
| `python -m pytest tests/ -q` | `179 passed in 91.94s (0:01:31)` | 0 |
| `python -m pytest harness-core/tests -q`（补充） | `171 passed in 42.45s` | 0 |
| `python tools/workbench.py doctor` | 全项 PASS，唯一 `[WARN] Claude Code: 未找到 — PATH 上无 claude` | 0 |
| `python tools/check_docs_drift.py` | `docs drift gate: PASS (29 check groups, 0 failures)` | 0 |
| `python tools/check_hygiene.py` | `hygiene PASS (no personal paths, no secret shapes)` | 0 |
| `python tools/check_public_surface.py` | `public surface: PASS (0 breaking, 18 additive)` | 0 |
| `python tools/check_ecc_provenance.py` | `manifest OK (74 files)` | 0 |

- ECC Manifest 校验路径存在且通过：`vendor/ecc/MANIFEST.sha256` + `tools/check_ecc_provenance.py` +
  `tests/test_ecc_provenance.py`（含于 179 中）。合计 179+171=350，与 CHANGELOG 计数 350/179 一致。
- 18 条 additive = checkpoint/plan/snap/verify 系列新增 CLI 命令，0 breaking。
- 唯一失败项：无。`claude 未找到` 为**环境问题**（本 bash 会话 PATH 无 claude），非回归。

**结论：PASS，无真实回归。**

## 三、Windows 兼容（含空格/中文路径）

- doctor（`python tools/workbench.py doctor`）四连跑全部 `EXIT: 0`：
  - `cd "$TMP/aiwb test dir" && python …/workbench.py doctor` → 输出正常，含中文行（如 `[PASS] git: 可用`）。
  - `cd "$TMP/工作台测试" && python …` → 同上。
  - PowerShell 两种路径：`powershell -NoProfile -Command "Set-Location -LiteralPath '…'; python … doctor"` → 两次均 `PS-EXIT=0`。
- install 幂等（目标含中文+空格：`…\工作台测试\aiwb test install`）：
  - 第 1 次：`[OK] 111 个文件`，exit 0；`status` 报 `files_owned: 111, version 0.1.0-preview.4, gate_mode: audit`。
  - 第 2 次：`[INFO] 已安装 v0.1.0-preview.4 (…) — 幂等刷新文件` + `[OK] 109 个文件`，exit 0。**无重复/损坏报错。**
  - 差异仅 2 文件：`PROJECTS.md`、`harness-data/gate.json`——设计上二次安装不重写（用户数据/永不复写），
    两文件均仍在盘上；但二次后 manifest owned 由 111 变 109（LOW 记录：受影响 UNINSTALL 清单）。
  - 卸载：无 `--yes` → 仅提示确认 exit 0；`--yes` → `[OK] 移除 109 个文件`，残留 3 个（gate.json、
    install-manifest.json、PROJECTS.md，均为设计保留）；`--yes --purge-data` → `[OK] 移除 0 个文件; 数据已清除`，
    目标目录确认不存在。
- git worktree：临时 repo `…/aiwb wt test/base`（路径含空格）→ `git worktree add "…/wt one" -b feat-one` OK →
  在 worktree 内 commit OK → `git worktree remove` OK，目录只剩 `base/`。

**结论：PASS**（附 1 条 LOW：二次 install 后 manifest owned 数量缩减，卸载保留 2 个数据文件属设计）。

## 四、多项目隔离（A/B 真实操作 + 哈希证据）

- 建 A=`$TMP/aiwb-proj-a`，B=`$TMP/工作台测试/proj-b`（独立 `git init`、不同 CLAUDE.md 与测试文件、各自 commit）。
  同一 `HARNESS_DATA_DIR=$TMP/aiwb-harness-data`。
- 先对 B 全树 sha256（29 文件含 `.git`）→ `b_before.sha256`。
- 对 A 执行：`checkpoint begin/save(--exec dev --payload {"proj":"A"})` · `plan "…" --save --exec task-a --cwd A` ·
  `snap save --cwd A --exec dev`（`file_count: 2`，ref `refs/harness/snaps/dev/1`）· `git add/commit`（`ed575a7`）。
- 对 B 执行同名 exec：`checkpoint save --exec dev --payload {"proj":"B"}` → A/B project_id 分别为
  `git:local:67f0460726b2ef94` / `git:local:d1d8c9336a892a26`。
- 隔离实测：`checkpoint load --exec dev --cwd A` → `payload {'proj': 'A'}`；`--cwd B` → `{'proj': 'B'}`；
  `--project-id git:local:67f…`（显式）→ A ✓。三项互不串写/串读。
- **`checkpoint list` 为 store-wide reader**（无 scope 参数，cli.py:154，设计注释 cli.py:533-541）：
  同时列出 A、B 两个 exec 行（各带 project_id）——与任务书"list 互不可见"的字面表述不符，属设计选择；
  内容读取隔离成立。记 LOW。
- B 零变化证据：`hash_tree.py` 前后对比 `diff` 为空 → `IDENTICAL: B tree byte-for-byte unchanged (29 files incl .git)`；
  B `git log` 仍 `cc3f4c1 init B`、`status --porcelain` 空（clean）。

**结论：PASS（B 零变化，数据归属隔离成立）；附 1 条 LOW（list 全局可见）。**

## 五、安全攻击面（静态核查 + 实测）

1. **硬编码 secret**：`harness-core/ tools/ hooks/` 生产代码 0 命中；全仓仅测试夹具
   （`AKIA…EXAMPLE` 于 tests/test_security_scan.py、`sk-…` redaction 用例于 harness-core/tests/test_contracts.py）。
   仓库自检 `check_hygiene` 同报 "no secret shapes"。**PASS**。
2. **gate 拦截**：`hooks/harness_gate.py` 存在，install 模板接入 PreToolUse(Bash)。实测钩子本体：
   - ENFORCE + `git push origin main` → stderr `[harness-gate ENFORCE] blocked irreversible/high-risk command
     (matched: \bgit\s+push\b)`，**exit 2**；安全命令（`ls -la`）exit 0。
   - 损坏 `gate.json` + ENFORCE → `fail-closed: config unreadable`，exit 2（不可静默绕过）。
   - **默认档**：install 模板 `GATE_DEFAULT.mode = "audit"`（workbench.py:102-118）——只记录不拦截，
     gate.py:5-7 自述 "THIS IS NOT PROTECTION"；裸 CLI 无 gate.json 时 `load_config` 返回 `mode "disabled"`
     （`gate check "git push origin main"` → `{"decision": "allow", "mode": "disabled"}`）。
   - `gate mode`（任务书原命令）缺 `--set` → argparse 报错 exit 2（该子命令是 setter；读取有效档位用 `gate check`）。
   - **拦截逻辑存在且实现正确，但默认非 ENFORCE**：装后默认 audit（观察态）、未安装时 disabled。
     与"默认不关闭"的强读不一致，如实记录为 NOTE（拦截能力有，默认不拦）。
3. **网络/遥测**：`telemetry.py` 仅追加本地 `<data-dir>/telemetry.jsonl`，字段 `{ts, cmd, project_id, argv, source}`；
   reader 命令自排除、`log()` 永不抛错（telemetry.py:33-54）；无任何外发。harness CLI / hooks 无网络导入。**PASS**。
4. **Token 观测实际字段（可读到的事实）**：
   - telemetry：仅调用计数（ts/cmd/project_id/argv/source），**无 token 数**；
   - bench result JSON（实测 batch2_t5_fusion.json）：`total_cost_usd, num_turns, duration_ms, is_error,
     skill_tool_calls, permission_denials, model, tier` 等；
   - `analyze_transcript.py`：assistant turns、按名工具调用、Task(子 Agent) 调用数、Skill 调用数、harness CLI 调用数。
   - **输入/输出/缓存读写 token 字段在 telemetry 与 bench 中均不存在**（grep 0 命中）——不可读到，
     因此本基线**不给出任何节省百分比**。**PASS（事实核查完成）**。

## 汇总

| 任务 | 结论 |
|---|---|
| 一 FAST 基线 | PASS（数字见上表） |
| 二 契约回归 | PASS（350 passed，检查脚本全 0） |
| 三 Windows 兼容 | PASS（附 LOW：二次 install manifest 111→109） |
| 四 多项目隔离 | PASS（B 全树 byte-identical；附 LOW：checkpoint list 全局） |
| 五 安全面 | PASS（附 NOTE：gate 默认 audit 不拦截；无 token 级观测字段） |

验收口径建议：新增组件"关闭状态"对比本表——hooks 数不变、MCP 不变、常驻进程 0、启动路径网络 0、
`pytest tests/ -q` 仍 179 passed、四个检查脚本仍 exit 0。
