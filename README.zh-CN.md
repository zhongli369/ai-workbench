# AI 工作台

*面向 Claude Code 的统一、带记忆的工程工作台。*

**这是什么。** 一层安装在 [Claude Code](https://claude.com/claude-code) 之上的薄工作台 — 不是又一个 Skills 大合集。一次启动, 指向任意项目; 它记住过去失败的原因; 小任务保持便宜。

**解决的痛点。** ①多个仓库来回切换, 每次会话都要重建上下文; ②同一个 bug 调试两遍, 因为上周的根因没人记下来; ③能力包让每条提示词都为今天用不上的规则付费。

**区别在哪** — 按来源诚实拆分:

| | 原生 Claude Code | everything-claude-code (ECC) | AI 工作台 |
|---|---|---|---|
| 单项目内改代码/测试/交付 | ✔ (CC 本身) | | |
| 60+ agents / 240+ skills 目录 | | ✔ (上游项目) | |
| 精选 ECC 子集, 按需非常驻 | | | ✔ (27 skills / 16 agents, 已 pin) |
| 一个工作台操作多项目 | | | ✔ (自研) |
| 跨会话失败记忆 + 重错 oracle | | | ✔ (自研, harness-core) |
| FAST/STANDARD/DEEP 成本策略 | | | ✔ (自研) |
| 不可逆命令三档闸门 | | | ✔ (自研) |

**安装** (Python ≥ 3.10 + Claude Code CLI; Windows 主测, Linux/macOS 走 CI):

```bash
git clone <本仓库> && cd ai-workbench-rc
python tools/workbench.py doctor
python tools/workbench.py install && python tools/workbench.py launch
```

**看真实演示** — 三个可复现 demo (离线可验收):
[1 · 一个工作台, 两个规则冲突的项目](docs/demos.md#demo-1) ·
[2 · 会话 A 记录的失败在会话 B 被复用](docs/demos.md#demo-2) ·
[3 · 多文件功能 + 按需能力](docs/demos.md#demo-3)。
实测数字(包括不好看的): [性能](#诚实的性能说明)。

```
workbench/            ← 在此启动 Claude Code; 自动加载工作台 CLAUDE.md
harness-core/         ← 自研: 失败存储 / 闸门 / telemetry (纯 stdlib, 27 项契约)
hooks/                ← PreToolUse 闸门 hook (ENFORCE 模式 fail-closed)
vendor/ecc/           ← 第三方: everything-claude-code 快照 (MIT, pin 已记录)
tools/workbench.py    ← 安装器 / doctor / 启动器 / 卸载器
```

## 七个差异化

| # | 差异点 | 机制 |
|---|---|---|
| 1 | 一个入口操作多项目 | 启动一次, 免 cd 跨项目工作 (绝对路径, `git -C`) |
| 2 | 目标项目规则正确加载 | 项目级 `claudeMdExcludes` 防止全局规则包遮蔽目标项目自己的 CLAUDE.md |
| 3 | ECC 能力按需调用 | 27 skills / 16 agents 来自 everything-claude-code, 按任务加载非常驻 |
| 4 | 跨会话失败记忆 | `harness-core` 记录失败原因; 遇到失败时 (fail-triggered) oracle 先查历史 |
| 5 | 复杂度匹配的 token 策略 | FAST / STANDARD / DEEP: 小修不规划、不起 agent、不记账 |
| 6 | 确定性质量与安全 | 42 项离线契约; 三档闸门 (DISABLED / AUDIT / ENFORCE) 管不可逆命令 |
| 7 | 目标项目零侵入 | 工作台装一次, 目标项目不被修改 |

## 安装

要求: **Python ≥ 3.10**, Claude Code CLI。Windows 是主要实测平台;
Linux/macOS 走 CI 覆盖的 POSIX 路径。

```bash
git clone <本仓库>
cd ai-workbench-rc
python tools/workbench.py doctor                      # 预检, 不做任何修改
python tools/workbench.py install --scope standalone  # 默认装到平台数据目录
python tools/workbench.py launch                      # 打印确切启动命令
```

作用域: `standalone` (默认, 独立目录) · `project` (仓库内 `.ai-workbench/`) ·
`user` (只打印手动步骤 — **绝不**静默改全局配置)。

卸载只删除本发行版拥有的文件 (由 `install-manifest.json` 追踪),
反馈数据默认保留, 除非显式 `--purge-data`:

```bash
python tools/workbench.py uninstall --yes
```

## 5 分钟快速上手

1. `python tools/workbench.py install --yes`
2. 运行 `python tools/workbench.py launch` 打印的命令
3. 在会话里指向任意项目: "修一下 D:\some\other\repo 里那个失败的测试"
4. 故意触发护栏: 让会话执行 "git push" — 观察 AUDIT 日志
   (切 ENFORCE: `python harness-core/harness/cli.py gate mode --set enforce`)
5. 下个会话失败记忆还在: `status` 显示累积记录数。

## 失败复用演示 (记忆的意义)

```bash
# 会话 1 — 失败发生并被记录
python harness-core/harness/cli.py feedback record \
  --project-id demo --cause permission_tool_mismatch \
  --summary "allowedTools 只写了 Bash(python:*) 但模型用的是 PowerShell 工具" \
  --source human-verified --confidence 1.0

# 会话 2 — 同类错误再现, 重试前先查
python harness-core/harness/cli.py feedback query --project-id demo --keyword allowedTools --json
# → 历史修复方案浮现; 同一次调试不付两次费
```

oracle 只在**遇到失败时** (fail-triggered) 或用户明确要求时查询, 不是每个任务开始都查。
(实测: 新鲜单缺陷任务默认先查 oracle 会使成本约翻倍且质量无增益。策略已固化这一点。)

## 诚实的性能说明

参考机实测 (Claude Code 2.1.x, `--output-format json` usage):

- **常驻上下文** (结构性对比, 与模型无关, `workbench benchmark` 实测):
  工作台 L0 ≈ 1.7k 字符; L0 + 全部 skill 索引 ≈ 9.0k 字符 vs 等效全局规则层
  ≈ 20.7k 字符 → **−57%** (仅 L0 则 −92%)。
- **固定琐碎提示词**: vnext $0.0199 vs baseline $0.0228 (同模型同提示词, N=1)。
- **任务级成本才是硬仗**: 首轮受控 bugfix A/B 实测 vnext 为 baseline 的 **2.33 倍**
  ($1.335 vs $0.569)。根因 = (a) 权限 pattern 试错 (b) 新鲜缺陷上误查 oracle。
  两项修复后受控复测 = **1.22 倍** ($0.540 vs $0.444, 双臂 PASS, 零 oracle 调用)。
  残余差距来自轮次行为, 非常驻上下文 (vnext 非缓存输入反低 62%)。尚未达到
  "≈ baseline" — 追踪在 `RELEASE_READINESS.md` (G4)。不利证据我们保留, 不删除。
- **全任务类型矩阵** (全部 N=1, transcript 已审计; 详见 `RELEASE_READINESS.md` G10
  与 `docs/POLICY_VERIFICATION.md`): 琐碎 **0.87×** · bugfix **1.22×** ·
  多文件特性 **0.84×** · 测试诊断 **1.81×** (fail-triggered 策略在空库上的成本
  ≈$0.34 — 这笔税同时也在为库填充经验; 同一臂把正确诊断自然写回了库)。
- **重复错误 oracle: honest-null, 如实披露。** 三组带预置失败史的受控对
  (含一组专为逼迫 oracle 设计的数据态根因场景) 中, 种子臂**从未查询过 oracle** —
  模型全部自诊修复, 有一次还独立选中了种子自己推荐的修法。机制
  (记录→存储→查询→项目隔离) 契约级验证通过, 策略也从未产生浪费性查询, 但
  in-vivo 检索收益**尚未证明**, 我们如实写明。oracle 的合理适用面 = 根因不在
  项目内任何可读之处的失败 (环境/配置/历史决策类)。

## 继承 vs 自研

| 组件 | 来源 |
|---|---|
| Skills / agents / commands (27+16+14) | **继承** — [everything-claude-code](https://github.com/affaan-m/everything-claude-code), MIT, pin 快照在 `vendor/ecc/` (见 `NOTICE`) |
| harness-core (feedback / gate / report / telemetry) | **自研**, 纯 stdlib, 确定性, 27 项契约 |
| 安装器 / 启动器 / 卸载器 | **自研** |
| FAST/STANDARD/DEEP 成本策略 | **自研**, 由上述实测驱动 |

## 安全语义 (依赖闸门前必读)

- `DISABLED`: 闸门不工作。
- `AUDIT`: 记录并提示 — **这是可观测性, 不是防护**。
- `ENFORCE`: 配置的高危 pattern 未预授权即拦截 (TTL 授权); 配置不可读时 fail-closed。
- `claude --print` (非交互) 不执行 PreToolUse hooks — 闸门强制只对交互会话生效。
  2026-10 在 CC 2.1.x 上实证。

## 文档

- [README.md](README.md) — English
- [NOTICE](NOTICE) — 第三方归属与 ECC pin 理由
- [SECURITY.md](SECURITY.md) — 威胁模型与漏洞报告
- [CHANGELOG.md](CHANGELOG.md) — 发布历史
- [RELEASE_READINESS.md](RELEASE_READINESS.md) — 逐门禁 PASS/FAIL/PENDING 状态
- [harness-core/README.md](harness-core/README.md) — 记忆/安全工具包, 可独立使用

## 许可证

MIT (本发行版自有代码)。everything-claude-code 由其作者以 MIT 授权 —
见 `vendor/ecc/LICENSE` 与 `NOTICE`。
