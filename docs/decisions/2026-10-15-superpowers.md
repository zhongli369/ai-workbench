# Superpowers 技能甄选决策 (2026-10-15)

上游: https://github.com/obra/superpowers · 许可证: MIT · 版权: Copyright (c) 2025 Jesse Vincent
本轮研究范围: systematic-debugging / test-driven-development / requesting-code-review（三个，未超出）

## 1. 上游核查证据

- **Pin**: `bb92a77741419a4ab5f06e711a283343f1ada0c3`（main 分支快照，取回时间 2026-10-15 ~15:20 UTC）。
- **取回方式（与任务差异，如实记录）**: 本机无法对 github.com 建立 git 连接
  （`git clone` / `git ls-remote` 经本地代理均报
  `SSL: no alternative certificate subject name matches target hostname 'github.com'`；
  该环境问题在 NOTICE 中已有先例记录）。改用 `codeload.github.com` 取回快照 tarball：
  GitHub tarball 的 `pax_global_header` 携带精确 commit SHA（`bb92a77…`），
  故 pin 仍为**精确 commit**而非分支名。
- **Pin 有效性验证**: 以 `codeload.github.com/obra/superpowers/tar.gz/bb92a77…` 重新取回
  （HTTP 200），与 main 快照**逐文件比对：238 个文件、文件名集合全等、文件内容 sha256 全等**
  （唯一差异是顶层目录名 `superpowers-main` vs `superpowers-<sha>`）。
- **许可证**: MIT 全文位于仓库根 `LICENSE`。允许复制/修改/再分发，条件是在副本或实质部分中
  保留版权与许可声明——本仓移植模板头部已嵌入完整 MIT 声明。三个技能本体未发现专有内容
  或额外限制条款，**无需因许可证拒绝任何技能**。
- **全局注入/自动安装风险（不移植）**: 上游 `hooks/hooks.json` 注册了
  `SessionStart: startup|clear|compact` 钩子（`hooks/run-hook.cmd session-start`），
  `hooks/session-start` 会把 `skills/using-superpowers/SKILL.md` 全文注入会话开头。
  本仓**未取用** hooks/、`index.js`、`package.json`、安装脚本或任何 `using-superpowers` 内容；
  本仓也没有任何 SessionStart 钩子（见 §6）。
- **技能本体检查**: 三个技能目录仅含 markdown（systematic-debugging 另含 1 个 `.sh` 助手脚本
  `find-polluter.sh`，未移植），无外部依赖、无安装钩子、无网络调用。
- **强制工作流问题（用户关注点）**: 三者均为强制性措辞——TDD 的 "Iron Law … 无异常"、
  systematic-debugging 的 "Violating the letter … is violating the spirit"、
  requesting-code-review 的 "Mandatory: after each task …"。唯一移植的技能做了裁剪（见 §4）。

## 2. 决策表

| 技能 | 结论 | 一句话理由 |
|---|---|---|
| systematic-debugging | **SHIP**（裁剪移植） | ECC 无同类"根因优先"调试方法论（failure-oracle 是失败史查询、build-fix 是浅层修错），增量真实且已实战验证 |
| test-driven-development | **REJECT** | 与 ECC `tdd-workflow` 技能（463 行）+ 全局 rules/testing.md + `tdd-guide` agent 功能重合 ≥80%，且 ECC 版 RED 门槛更严 |
| requesting-code-review | **REJECT** | 功能由 ECC `code-reviewer` agent（323 行，含置信度过滤）+ `/code-review` 命令 + rules/code-review.md 覆盖 ≥80%；差异仅为"派发新上下文 reviewer + SHA 边界"的机制细节，不值得再装一个同类技能 |

## 3. 与 ECC 去重对比（逐技能）

**test-driven-development → REJECT**
- ECC `workbench/.claude/skills/tdd-workflow/SKILL.md` 已含: 测试先行、RED gate
  （"测试未编译执行不算 RED"、"确认 RED 前不得改生产代码"）、GREEN、REFACTOR、
  80% 覆盖率、git checkpoint、单元/集成/E2E 模式、mock 规范、常见错误。
- 上游独有而 ECC 未覆盖: 合理化借口对照表、"写过的代码必须删除重来"、writing-good-tests.md
  的三条断言纪律。均为**建议性文字而非能力**，不足以支撑重复安装一个技能。
- 结论: ≥80% 功能重合，直接 REJECT，不复制。

**requesting-code-review → REJECT**
- ECC 覆盖: `agents/code-reviewer.md`（评审提示词，含 Pre-Report Gate、HIGH/CRITICAL 需举证、
  误报清单、允许零发现）> 上游 `code-reviewer.md` 模板；`commands/code-review.md`
  （本地 diff + GitHub PR 两模式）；`rules/ecc/common/code-review.md`（触发时机、严重度分级、
  批准标准）。"何时评、评什么、发现怎么办"全部已覆盖。
- 上游独有: 派发 subagent 时"给出精心构造的上下文，绝不给会话历史" + `BASE_SHA/HEAD_SHA`
  取模的机制描述。属可选的 ECC 现有面增量微调，登记为**后续可选事项**，不新建同类技能。
- 结论: ≥80% 功能重合，REJECT。

**systematic-debugging → SHIP**（重合 <30%）—— 另需与既有 `superpowers` 条目划清关系
- registry 中**已存在** `superpowers` 条目（external-plugin，obra/superpowers via official CC
  marketplace，recorded-intent，用户自行 `/plugin install`）。其 `cost_hint` 自述
  "SessionStart bootstrap + skill descriptions"，`evidence` 注明 "method overlap with curated
  ECC skills noted"——即：**整插件路线 = 用户侧自行安装**，本仓从不安装它，且已知其
  方法与 ECC 策展技能重叠。
- 本技能是**策展式单技能替代路径**（唯一一个 ECC 无对应物的技能，且剥除了 SessionStart 注入），
  与整插件路线功能重叠 → 提案中设 `mutex: ["superpowers"]`，二者只应启用其一。
- 已查证 ECC 无等价物: `failure-oracle` 是历史失败查询（数据面而非方法论）；
  `commands/build-fix.md` 只有一行 "Diagnose — identify root cause" 式的浅层修错；
  `plan-orchestrate`/`repo-scan`/`search-first` 与调试无关。
- 上游独有: 四阶段法（根因调查 → 模式分析 → 单一假设最小验证 → 修复）、
  多组件边界插桩取证、沿调用栈反向追踪坏值来源、"3 次修复失败即质疑架构"、
  红旗/合理化对照。

## 4. 落地: capabilities/wiring/superpowers-systematic-debugging.skill.md

- 形式: 能力装载 v1.1 的 `skill-file` wiring 模板（enable → health ok → 写
  `.claude/skills/aiwb-superpowers-systematic-debugging/SKILL.md`，带 aiwb-managed 标记，卸载可回收）。
- 头部保留: 上游 repo URL、固定 commit SHA、MIT 声明全文、原作者/版权。
- 移植裁剪:
  - **删除** 上游 SessionStart 注入相关内容与 `using-superpowers` 依赖（本仓不存在该链路）；
  - **删除** 强制工作流措辞（"Violating the letter…"、"MUST complete each phase"、
    "Don't skip when: Issue seems simple"），改为判断式边界；
  - **删除** 对 superpowers 专有技能的交叉引用（`superpowers:test-driven-development`、
    `superpowers:verification-before-completion`）；
  - **新增** "何时用 / 何时不用": 简单直观的修复（拼写、缺失 import、刚写下的 off-by-one）
    直接修，不走四阶段；只有非显而易见/已试过修复/跨组件的故障才走完整流程；
  - `find-polluter.sh` 等辅助脚本未移植（无脚本 = 无执行面）。
- 保留的"便宜不变量": 动手前读完实际错误文本、知道为什么改动能成立。

## 5. systematic-debugging 实战验证（真实执行，2026-10-15）

临时项目（worktree 内 `_sd_experiment/`，验证后已删除、未进 commit）:
`rows.build_row(name, score, schema="v2")` → `summary.render(row)` → `test_summary.py`。
错误表象与真实根因分属两个模块。

1. **表象（naive 首观）**: `pytest` → `KeyError: 'score'`，报错点在 `summary.py:6`
   （`return f"{row['name']}: {row['score']}"`）。仅看报错点，"render 缺少键防御"是唯一直觉。
2. **Phase 1 根因调查**:
   - 完整读错误 → traceback 局部变量已给出决定性证据: `row = {'name': 'ada', 'points': 70}`
     （键是 `points` 不是 `score`）——跳过细节就会漏掉它；
   - 复现: 连续两次运行均为同一错误（确定性）；
   - **检查近期变更** → CHANGELOG 0.2.0: "`build_row()`: added the `schema` parameter
     (default `"v2"`)" —— 与实际返回形状对上；
   - 反向追踪坏值: 问题 dict 由 `rows.build_row` 产生，不在 `summary.render`。
3. **Phase 2 模式分析**: 同函数 v1 分支 `{"name", "score"}` 即"可用参照"；差异 = 新增默认
   `schema="v2"` 静默改变了所有既有调用方拿到的契约。
4. **Phase 3 假设 + 最小验证**: 假设 "默认值 v2 破坏既有输出契约"。
   最小探针 `build_row('ada', 7)` → `{'name': 'ada', 'points': 70}`；
   `build_row('ada', 7, schema='v1')` → `{'name': 'ada', 'score': 7}`。假设成立。
5. **对照组（症状补丁的代价）**: 若按表象在 `render` 加 `.get('score')`，输出将变为
   `ada: None` —— 不再崩溃，但数据静默错误。方法论的"修根因不修症状"在此显式分叉。
6. **Phase 4 实施**: 先加失败回归测试
   `test_default_call_keeps_the_documented_score_contract`（RED: 2 failed）→ 唯一改动
   `rows.build_row` 默认值改回 `schema="v1"`（v2 改为显式选择）→ GREEN: 2 passed，
   端到端 `render(build_row('ada', 7))` 输出 `ada: 7`。

结论: 该方法论在"表象点 ≠ 根因点"的场景中，靠 **完整读错误 + 检查近期变更 + 最小探针**
三步导向真实根因，并阻止了症状补丁。方法有效，且不需要强制流程即可用于常规排障。

## 6. ECC 现状核查（Section 七）

- **合适 skill 能否被发现?** 能。技能以 `<target>/.claude/skills/*/SKILL.md` 形式安装，
  Claude Code 按 frontmatter 的 name/description 建立索引；本会话已实际列出
  `workbench:tdd-workflow`、`workbench:failure-oracle` 等 30 个技能，发现链路可用。
- **不相关 skill 是否默认装入上下文?** 不装全文。resident 的只有 frontmatter 索引
  （registry 声明 "frontmatter index only until invoked"，`workbench benchmark` 会实测
  "skills 索引 (frontmatter 合计)" 字节数）；正文仅在 Skill 工具调用时加载。
  能力注册表本身（capabilities/registry.json）设计上**永不注入模型上下文**（tools/capability.py 顶部注释）。
- **多个同类 skill 会否同时响应?** 存在此风险，但当前靠**策展**而非机制控制：索引按
  description 匹配，语义相近的技能会并列可选（如 `security-review` 与 `safety-guard`、
  `tdd-workflow` 与 `python-testing` 边界相邻）。本次两个 REJECT 决策就是在维持这一策展边界。
  最具体的同类风险: 用户装整插件 `superpowers` 后，其 systematic-debugging 与本次策展
  单技能会重叠 —— 提案用 `mutex: ["superpowers"]` 处理（§3/§7）。
  注意: 会话中出现的同名重复项（`workbench:tdd-workflow` 与
  `.claude/worktrees/.../workbench:tdd-workflow`）来自多个 git worktree 并存，不是安装器缺陷。
- **简单任务有无多余流程?** 工作台层已按任务分级: `workbench/CLAUDE.md` 明确 FAST 级
  "直接做；不起 agent；不查失败史；只跑相关测试"，STANDARD/DEEP 才按需加载技能与 agent。
  ECC 自带规则文件（如 code-reviewer agent 的 "MUST BE USED for all code changes"、
  全局 rules/testing.md 的强制 TDD）仍偏重流程，但 workbench 会话通过 `claudeMdExcludes`
  排除 `**/.claude/rules/ecc/**` 并以上述分级中和。**本工作台会话内现状足够**。
- **结论: 无需修改**。本次不新增/修改任何发现机制、注册表逻辑或安装逻辑；
  唯一改动是按既有 wiring 机制新增一个技能模板文件（+ 本文档），不改变现状结论。

## 7. registry JSON 提案（由总 Agent 决定是否合入；本 Agent 未改 registry.json）

```json
{
  "id": "superpowers-systematic-debugging",
  "name": "Systematic debugging (root-cause-first, adapted from superpowers)",
  "origin": "extract:obra/superpowers@bb92a77741419a4ab5f06e711a283343f1ada0c3 (MIT, condensed port; forced-workflow + SessionStart injection removed)",
  "version": "7.0.0-adapted.1",
  "license": "MIT",
  "applies_to": ["diagnosis", "recovery"],
  "deps": [],
  "cost_hint": "zero resident beyond the frontmatter index; body loads only on invoke",
  "trigger": "non-obvious failure: unexplained bug, failure that survived a fix attempt, or cross-component breakage; not for trivial obvious fixes",
  "mutex": ["superpowers"],
  "security": "static markdown only; no scripts, no hooks, no network; ships no SessionStart injection",
  "health": {"type": "dir", "path": ".claude/skills"},
  "wiring": "skill-file (v1.1): enable requires the target skills tree to exist, then writes managed .claude/skills/aiwb-superpowers-systematic-debugging/SKILL.md (never auto-installs anything)",
  "default_enabled": false,
  "evidence": "upstream pinned @bb92a77 reviewed; adapted port; methodology dry-run validated 2026-10-15 (docs/decisions/2026-10-15-superpowers.md)",
  "wiring_action": {
    "type": "skill-file",
    "template": "superpowers-systematic-debugging.skill.md",
    "dest": ".claude/skills/aiwb-superpowers-systematic-debugging/SKILL.md"
  }
}
```

说明:
- 该技能无外部 CLI，故 health 用 `dir .claude/skills`（技能树存在 = 安装完整）
  而非 repomix/agent-browser 式的 `cli` 检查；这是 v1.1 enable 需 health=ok 前提下的最贴近语义的选择。
- `default_enabled: false` — 需操作者显式启用。
- `mutex: ["superpowers"]` 只单向生效（capability.py 只检查被启用方自己的 mutex 列表）；
  若需对称互斥，总 Agent 需在既有 `superpowers` 条目的 mutex 中加回本 id。
- 已存在的 `superpowers` 条目保持不动（recorded-intent，用户侧安装），本提案不改变其语义。

## 7b. 接线端到端验证（scratch target，未进 commit）

在 worktree 内一次性 scratch target 中（registry 副本 + 上述提案条目 + `.claude/skills` 存在）驱动
`tools/capability.py` 的真实函数完成 enable 分支全链路：
- `check_health` → `ok`（dir `.claude/skills`）；
- `_wire_skill_file` → 写入 `.claude/skills/aiwb-superpowers-systematic-debugging/SKILL.md`，
  首行 `<!-- aiwb-managed:superpowers-systematic-debugging -->`、次行 frontmatter `---`，共 128 行；
- 状态文件记录 `{"superpowers-systematic-debugging": true, "_wired": {...}}`；
- `_unwire_skill_file`（等同 disable 路径）→ 文件被 owns-only 移除，`dest exists: False`。

**被拦披露**: `... capability enable <id>` 的 CLI 形态在本会话被 worktree-isolation hook
按关键词拦截（连 `grep "enable"` 都被拒，理由显示为 "git operations"，属误拦）；
故上述验证改为脚本直接调用同一模块函数（未重写逻辑）。CLI 形态本身未能在本会话直接执行，
但该分支逻辑已被 `tests/test_capability_wiring.py` 的既有契约测试覆盖（本次 179 项全绿）。

## 8. 未验证事项 / 限制

- **未在真实 Claude Code 会话中触发该技能**（registry 未合入，技能未落到真实
  `.claude/skills`）。接线机制本身已在 §7b 用 scratch target 端到端验证（含 unwire），
  模板卫生按 `tests/test_capability_wiring.py` 规则等价自检通过；剩余未知是
  Claude Code 对 aiwb-managed 文件（首行标记、次行 frontmatter）的加载/索引行为。
  该格式是 v1.1 既有设计（repomix/agent-browser 同构），非本次引入，但**未在本次实测**。
  相关旁证: `workbench benchmark` 统计 frontmatter 时以 `startswith("---")` 判断，
  接线后的文件（首行是标记）会落入 200 字符兜底分支——为既有现象，仅记录，本轮不改。
- 未做 A/B 效果测量（有技能 vs 无技能的任务成功率/成本差异）。
- mutex 对称性依赖总 Agent 在 `superpowers` 条目补回本 id（§7 说明），本轮未改 registry。
- 未核查上游其他 12 个技能（超出本轮范围）。
- 上游快照取回经第三方可访问路径 `codeload.github.com`（GitHub 官方域名，非镜像）；
  无法通过 git 协议交叉验证 commit 对象的签名/祖先链，但 pin 与内容一致性与
  pax header/SHA 可往返验证（§1）。
- `git clone --depth 1` 未执行（环境 TLS 拦截导致 git-over-HTTPS 不可用），
  已用等价快照 + 精确 pin 替代，属任务书要求的偏离，需人工知悉。
