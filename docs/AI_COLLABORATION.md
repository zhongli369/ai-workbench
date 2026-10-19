# AI 双引擎协作协议（Codex × Claude Code）

状态：active（2026-10-19 初始化）
适用范围：本仓库（AI Workbench）的所有开发任务。

入口分工：

- `AGENTS.md`：Codex 的项目入口与开发命令。
- `CLAUDE.md`：Claude Code 的项目入口。
- `docs/AI_COLLABORATION.md`：双方共享的协作约定（本文件）。
- `workbench/CLAUDE.md`：安装后的工作台会话策略，是产品载荷，不是本仓库的
  开发规则。

三份入口文件只引用共享规则，不复制整段规则。

## A. 单一事实来源

1. **代码实现**：以仓库实际代码为准。
2. **产品说明**：以 `README.md`、`README.zh-CN.md` 和现有 `docs/` 为准；
   README 中的历史发布链接不等于当前开发版本。
3. **任务完成**：以真实测试输出、退出码和 Git 证据为准；不以模型自述、
   测试数量或另一个模型的报告代替。
4. **项目规则**：`AGENTS.md` 负责 Codex 入口，`CLAUDE.md` 负责 Claude Code
   入口，本文件负责共享协作约定。仓库外更高层级的用户指令优先。
5. **门禁命令**：以 `.github/workflows/ci.yml`、`.github/workflows/security.yml`
   和 `AGENTS.md` 的验证命令表为准；文档与 CI 不一致时先修文档。

## B. 工作分工

Codex 与 Claude Code 地位平等，都有权开发任意模块。分工按实际任务和已占用
文件决定，不做永久固定。

推荐流程：

1. 明确任务目标、验收标准和影响范围。
2. 分配模块或文件所有权，记录在任务说明或交接消息中。
3. 建立独立分支；并发开发时使用独立 worktree。
4. 双方并行开发，不写对方正在写的同一工作区。
5. 各自运行与改动相关的测试和静态检查。
6. 交换分支、提交 SHA 或 Diff。
7. 交叉审查真实代码和测试证据。
8. 只处理有证据的问题，不因模型身份接受或拒绝建议。
9. 集成后运行共同门禁（受影响的契约 + 静态检查）。
10. 正常合并；不 force push，不擅自合并到 `main`。

推荐的隔离方式：

```powershell
# Codex 或 Claude Code 各自在仓库外创建独立 worktree
git worktree add ..\ai-workbench-rc-<owner> -b <owner>/<topic> main

# 结束任务后清理（确认没有未提交/未推送内容）
git worktree remove ..\ai-workbench-rc-<owner>
```

不要为协作新建 Agent 调度框架、任务数据库或常驻服务。已有
`harness checkpoint` / `verify` / `snap` 按需复用。

## C. 文件所有权

默认规则：当前任务 owner 拥有其声明的文件；未声明时先协调，不能假设
“没人正在改”。

| 范围 | 规则 |
|---|---|
| 业务代码、`harness-core/`、`tools/`、`hooks/` | 由当前任务 owner 声明；同一时间只允许一方修改同一组文件 |
| `docs/surface.json` | 共享冻结面；只能通过 `python tools/check_public_surface.py --accept-new --bump ... --rationale "..."` 更新，不手改 |
| `AGENTS.md`、`CLAUDE.md`、本文件 | 共享治理文件；修改前先协调，改后交叉审查 |
| `.github/workflows/`、`SECURITY.md`、`hooks/harness_gate.py`、gate 决策语义 | 高风险；需要明确任务、测试证据和安全审查 |
| `vendor/ecc/**` | 上游固定快照；不手改，按 pin 升级并保留许可证/NOTICE |

同一模块必须双方修改时，串行执行：一方完成、提交、给出 SHA；另一方基于该
提交继续。禁止两个模型同时写同一个 Git 工作区。

## D. 交接格式

每次任务结束时使用以下短格式，放在最终回复、提交说明或交接消息中：

```text
TASK:
OWNER:
BRANCH:
BASE SHA:
CHANGED:
TESTED:
RESULT: PASS / FAIL / PARTIAL
RISKS:
NEXT:
```

要求：

- `TESTED` 写实际执行的命令和关键结果，例如
  `python -m pytest tests/ -q -> 276 passed`；未执行写 `UNVERIFIED`。
- `RESULT` 不能把环境缺失、跳过或被 gate 拦截写成 PASS。
- `NEXT` 只写下一位开发者真正需要做的事，不写泛泛计划。
- 长任务优先复用已有 checkpoint；没有必要时不建立额外任务记录系统。

## E. 冲突解决

当两个模型给出不同建议时，按以下顺序判断：

1. 可复现实验或真实测试证据。
2. 项目实际需求与用户明确目标。
3. 更小、可回滚的改动。
4. 更严格的安全边界。
5. 更低的长期维护成本。

模型身份不是证据。若争议涉及产品方向、权限、外部发布或无法用现有证据
裁决，停止扩大改动，向用户报告备选方案和各自代价。

## F. 本轮初始化边界

- 只新增/更新仓库级协作入口与共享协议，不改业务代码、依赖、版本号、
  Hook、MCP 或后台进程。
- `workbench/CLAUDE.md` 是产品载荷，本轮不修改；它的内容继续由产品测试
  和发布流程约束。
- 远端推送和 PR 需要有效的 GitHub 凭据；凭据不可用时只准备本地分支和
  提交，并如实标记 BLOCKED，不绕过认证。
