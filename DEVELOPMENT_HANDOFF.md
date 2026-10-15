# AI Workbench — 开发交接（旧窗口终态）

生成：2026-10-15 · 旧开发窗口（退役项目 CodeLike 会话）收官交接。
以后正式开发主场 = 本仓库（ai-workbench-rc，本文件所在目录即仓库根）。

## A. Git 真实终态

- 仓库：ai-workbench-rc（本文件即在其根目录；本地无 remote，推送走 Git Data API 脚本）
- 分支：`main`，工作树干净，本地 == 远端（merge commit 经 sha1 自校验逐字节一致）
- **main SHA：以 `git log -1 main` 为准**（本文档自身亦是 main 上的提交，写死即过期）；
  永久锚点 = PR #2 合并提交 `552d126ecda4e1b60ba5e922edfec895aaff66dd`（GitHub 签名）
- PR #2：**MERGED** — https://github.com/zhongli369/ai-workbench/pull/2 （head `b7c3431e`）
- CI（PR 轮 @b7c3431e）：ci ✅ run 38725348735 · security ✅ run 38725348768
- CI（main @552d126e）：ci ✅ run 38727390540 · security ✅ run 38727390575
  https://github.com/zhongli369/ai-workbench/actions
- VERSION：`0.1.0-preview.3`（`tools/workbench.py:33` 单一来源）
- 已发布 Tag：`v0.1.0-preview.1`（e9c8a2d，**冻结，勿动**）；preview.3 未发 Release

## B. 当前真实能力

| 能力 | 状态 | 入口 / 说明 |
|---|---|---|
| State / Checkpoint | MERGED_AND_VERIFIED | `harness checkpoint save\|load`（load 需 `--exec`） |
| Plan | MERGED_AND_VERIFIED | `harness plan "需求"`（3 阶段原型，13 archetype） |
| Gate / Approval | MERGED_AND_VERIFIED | `harness gate mode`（DISABLED/AUDIT/ENFORCE） |
| Snapshot | MERGED_AND_VERIFIED | `harness snap save\|list\|diff\|verify\|restore\|prune`；restore 默认 dry-run，`--apply` 才写入；三方冲突 fail-closed；rescue ref 先行；**永不 `reset --hard`/`clean -fd`** |
| Verify | MERGED_AND_VERIFIED | `harness verify run --stage X\|status`；status 未 pass → `can_claim_done=false`；skipped=exit 3 不冒充 pass；reflection 有界（默认 3，硬顶 10） |
| Supply Chain | MERGED_AND_VERIFIED | `.github/workflows/security.yml` + `tools/security_scan.py`；trivy v0.75.0 sha256 pin；main/tags/release/PR-to-main 阻塞，其余 AUDIT；exit 3=infra 失败 ≠ PASS；报告只进 artifact |
| Oracle / 经验查询 | EXPERIMENTAL | `harness feedback query`——仅真实失败触发时按需查，不默认注入 |
| ECC instinct / hermes / caveman | EXPERIMENTAL | 仅 `experiments/` 隔离原型（27 测试），不进安装载荷，未升级为默认功能 |
| rtk token-killer | REJECTED | BUSL-1.1 许可证禁用，未集成，勿再引入 |

证据：`docs/CAPABILITY_EVIDENCE.md`（逐能力来源/触发/开销/退出方式/诚实限制）。
契约：harness-core 171 + tests/ 134 = 305 绿（CI 9 平台实测）；experiments/ 27 隔离不计入。
harness CLI 统一入口：`harness-core/harness/cli.py <subcommand>`。

## C. 开发规则

- 正式开发只用本仓库；SystemKernel / WorkFlow / CodeLike 已退役，禁止引用其入口。
- 全局指引 = 用户级工作区根 CLAUDE.md（41 行精简版，保持勿膨胀；备份 .bak-20261015 与其同目录）。
- Claude Code 原生执行优先；简单任务不启动大型规划；snap/verify/plan/gate 按需显式调用。
- 不重复造 Planner / Runtime / Router；默认 FAST，增强按需。
- 付费 Benchmark 需显式授权（上轮预算 $2.3365/$3.00 已封账）。
- 新功能必须有真实调用入口 + 测试 + 明确的失败行为；`skipped`/`continue-on-error`/零 job 永远不算 PASS。
- 禁止 force push；推送用 fusion 文档仓 launch 目录的 API 脚本（GH_TOKEN 经 `git credential fill` 注入，不打印）。
- 本地同步远端：github.com 直连被 DNS 污染；gitclone.com 镜像有缓存延迟；签名 merge commit 可按"API 元数据→重建裸对象→sha1 自校验→`merge --ff-only`"落地（tz +0800、gpgsig 空行→单空格续行、message 无尾换行；本窗口已验证）。
- **树卫生**：`tools/check_hygiene.py` 禁止任何机器绝对路径/密钥形状入库（本文件首版即因含构建机路径被 CI 拦截——门禁有效的实证）；写文档一律用仓库相对路径。

## D. 已知问题

1. **低 · snap 在非 git 目录不可用**：报 `{"status":"skipped","reason":"not-a-git-repo"}` exit 0，属设计内诚实限制（`docs/CAPABILITY_EVIDENCE.md`）。
2. **低 · supply-chain 门依赖漏洞库网络**：runner 无法下载 trivy DB 时 exit 3（阻塞态 fail-closed，AUDIT 态降级警告）；非缺陷，但网络分区时 release 会被挡——届时先查 run log 确认是 infra 而非真实 finding。
3. **低 · ARSENAL 开发残留未入仓库**：`_arsenal-worktrees\`（5 个 worktree，内容已全部并入 main）与 fusion 文档仓 launch 目录（API 推送/PR/CI 监视脚本，非 git 管理）；不影响 main 完整性，可按需清理。

## E. 下一步（最多 3 项）

1. **发 Release v0.1.0-preview.3**：main 已全绿，按 `RELEASE_READINESS.md` 走发布门禁（security.yml 会在 tag push 上阻塞执行，正好实战）。
2. **snap/verify 真实 dogfood**：在下一个真实多阶段任务中按需启用，收集误触发/漏触发证据，决定 EXPERIMENTAL 能力去留。
3. **清理 ARSENAL 残留**：确认 `_arsenal-worktrees\` 无未推送内容后归档删除；launch 脚本移入本仓库 tools/ 或归档。
