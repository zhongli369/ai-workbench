# AI 工作台 VNext

统一开发入口: 从本目录直接操作任意项目 (绝对路径读写 / `git -C` / `python -m pytest <dir>`)。
ECC 能力按需调用; harness-core 提供失败史、经验回流与执行保护。

## 安全底线 (不可协商)

1. **验证才说完成**: 每个实现阶段后实际执行验证 (编译/测试/运行), 展示真实输出再进下一步。无证据的"完成" = 失败。
2. 无硬编码密钥; 令牌走环境变量, 不进命令行参数; 错误信息不泄漏敏感数据。
3. 不可逆/高风险命令 (push / reset --hard / rm -rf / publish / deploy) 经 harness gate; ENFORCE 模式未授权即拦截, 不得绕过。
4. 边界输入必校验; 错误显式处理, 不静默吞错。

## 任务分级 (资源匹配, 不是越重越好)

- **FAST** (单文件小改 / 查询 / 明确指令): 直接做。不起 agent, 不全局扫描, **不查失败史**, 只跑相关测试, 不写经验记录。
- **STANDARD** (多文件 / 新功能 / 修 bug): 按需加载相关 Skill (tdd-workflow / python-testing / 语言 patterns); 改后必须验证。**查失败史的时机 (fail-triggered)**: ①遇到报错/测试失败/命令失败, 动手调试或重试之前——先查一次本项目历史, 命中即换方案不盲目重试 ②用户明确要求。**任务开始时不默认查** (实测: 新鲜任务默认查 ~2x 成本零增益)。失败明确后再回流, 微操作不记账。
- **DEEP** (架构 / 高风险 / 跨系统): 先 planner 或 architect 规划并明确验收标准; 允许查失败史与调专家 agent; 完成后 code-reviewer (+ 安全敏感时 security-reviewer); 完整测试证据。长时程/多阶段任务: `harness plan "<task>" --save` 生成确定性阶段+验收脚手架 (on-demand, 零模型成本), 各阶段用 `harness checkpoint begin/save` 留检查点, 支持跨会话恢复与 `checkpoint verify` 完整性校验。

- **RECOVERY** (仅当明确卡住): 信号 = 同一错误重复 / 修复后仍失败 / 缺项目外部状态 / 工具连续失败 / 无有效进展。动作 = 先 fail-triggered 查历史 → 缩小范围回主 agent → 收缩计划。**一次正常测试失败 ≠ 卡住, 不触发恢复链**。观察到空查询/无效 agent/重复规划时: 停查 oracle、停起子 agent、收缩上下文 — 但永不关闭安全检查和 gate。

telemetry 由 CLI 自动记录, 永不为此产生额外模型回合。

## 失败史与经验 (harness-core)

- 触发条件见上; 查询 → Skill `failure-oracle`; 回流 → Skill `experience-capture` (用户纠正必须记: `--source user-correction --confidence 1.0`)
- promoted 经验仅供人工审查, harness 永不自动修改规则或配置

## 能力发现 (按需, 不预载)

- **Skills**: 语言模式 (python-patterns) / 测试 (python-testing, tdd-workflow) / 安全 (security-review, safety-guard) / 研究 (search-first, deep-research) / 规划 (plan-orchestrate) / 前端 (frontend-patterns) / 上下文与成本 (context-budget, cost-tracking) / 学习 (continuous-learning-v2) — 用 Skill 工具按任务加载
- **Agents**: planner / architect / tdd-guide / code-reviewer / security-reviewer / build-error-resolver / python-reviewer / performance-optimizer / silent-failure-hunter / e2e-runner / harness-optimizer 等 — 仅 STANDARD+ 按需调用
- **跨项目操作模型**: Skill `workbench`

## 项目隔离

- 目标项目的 CLAUDE.md 不会自动加载; 开始操作前先显式读它
- harness 经验按 project_id 隔离; 不跨项目泄漏项目私密内容
