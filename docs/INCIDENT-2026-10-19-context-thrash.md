# 2026-10-19 Claude Code 上下文爆炸事故复盘

## 结论（先看这里）

这不是 "Skills 太多" 或 "Hook 输出太大"。主导项是 **MCP 工具 schema**：
该会话的 API 请求附带了 **259 个工具定义**，其中全局注册的 REA
（`rea-agents`）一个 server 就暴露 **207 个工具**。按 Claude Code 自己写入
transcript 的 `api-request-shape` 统计：

| 来源 | 工具数 | schema 字符数 | Token 估算（字符/4，仅估算） |
|---|---:|---:|---:|
| REA (`mcp__rea__*`) | 207 | 772,462 | ~193,115 |
| Claude Code 原生 | 28 | 64,258 | ~16,064 |
| Scrapling | 10 | 50,212 | ~12,553 |
| Codegraph | 8 | 6,518 | ~1,629 |
| claude-baton | 4 | 2,233 | ~558 |
| IDE | 2 | 998 | ~249 |
| **合计** | **259** | **896,681** | **~224,170** |

压缩边界的 `preTokens` 分别是 305,617 / 303,185 / 304,003。也就是说，
**仅工具 schema 就吃掉了约 3/4 的上下文窗口**，压缩后的摘要只有 6,902 /
7,473 / 7,404 tokens，剩下的空间几轮对话就会再次填满。这与客户端报错
"context refilled to the limit within 3 turns of the previous compact,
3 times in a row" 的方向一致。

## 证据

真实会话：`%USERPROFILE%\.claude\projects\F--...-ai-workbench-rc\ed9e....jsonl`
（2026-10-19 12:16–12:27 UTC，Claude Code 2.1.303）。

1. `api-request-shape` 记录中的 `shape.tools` 为 259 项；按 server 分组结果
   见上表。REA 的 `tool_count: 207` 也写在已安装 skill 的 frontmatter 中。
2. 三次 `compact_boundary` 均为 `trigger: auto`：
   - 12:21:05 — pre 305,617 / post 6,902
   - 12:23:39 — pre 303,185 / post 7,473
   - 12:25:36 — pre 304,003 / post 7,404
3. 客户端在第三次压缩后返回 `autocompact_thrash`，提示文件读取或工具输出
   可能对上下文窗口过大。实际主导项是常驻工具 schema，而不是某一次文件
   读取。
4. `instructions` attachment 在初始请求和每次压缩后各出现一次，共 4 次：
   用户级 ECC common rules、`RTK.md`、父目录 `CLAUDE.md`、自动记忆。
   这些合计约 17 KB（估算 ~4k tokens），并且是**压缩后的正常重注入**，
   不是客户端在一轮里自动注入了四份。它们不是本次爆炸的主因，但说明：
   直接运行 `claude` 时工作台的 `claudeMdExcludes` 没有生效。
5. `prompt_snapshot` attachment 单条约 1.08 MB，但它是诊断快照，不是
   API 请求上下文；不要把它误算成模型输入。
6. Web Search 的 403 出现 7 次，原文指向 Volcano Ark Console 的激活状态。
   这是 Provider 授权/兼容问题，与 MCP 数量、上下文余量无关。日志中没有
   看到无限重试风暴。
7. 一条 Bash 调用持续约 120 秒（12:25:52 → 12:27:52），属于慢命令；
   没有证据表明存在无界重试。
8. **项目 settings 里的 `strictMcpConfig` 不生效**：用临时项目 + 仅含
   `{"strictMcpConfig": true}` 的 `--settings` 文件实测（没有再传 CLI 的
   `--strict-mcp-config`），请求仍带 **255 个工具**（REA 207 个），并在
   289,863 tokens 时自动压缩到 3,313。Claude Code 2.1.303 只认 CLI 标志；
   因此修复必须落在启动器命令行，不能只写一个看起来合理的 settings 键。

## 配置来源

- Claude Code 2.1.x 的实际用户级 MCP 来源是 `%USERPROFILE%\.claude.json`
  的 `mcpServers`，不是 `%USERPROFILE%\.claude\mcp.json`。本次会话实际加载
  的是 `rea`、`scrapling`、`codegraph`、`claude-baton` 和 IDE 内置 server。
- `%USERPROFILE%\.claude\rules\ecc\common\*.md` 会被自动加载（User memory）；
  工作台安装时写入的 `claudeMdExcludes` 只对经过工作台启动器的会话生效。
- `%USERPROFILE%\.claude\skills\reverse-engineer-anything\SKILL.md` 自身写着
  "Connect only when needed"，并没有要求全局常驻注册 REA。

## 已做的修复

1. **启动器默认 MCP = 0**：生成的 `workbench.ps1` / `workbench.sh` 现在传
   `--strict-mcp-config`，忽略全局/用户级 MCP；仅当工作台根目录存在
   `.mcp.json` 时才追加 `--mcp-config`（默认 `capability enable` 的目标就是
   工作台安装根）。这保留了 Playwright 的按需接线，同时不会重新打开全局
   大工具集。
2. **只读上下文审计**：新增 `tools/context_audit.py`，从真实 transcript 的
   `api-request-shape`、`compact_boundary`、`instructions` attachment 统计
   工具 schema 与压缩事件；不输出消息正文、schema 正文或任何环境变量。
3. **doctor 只读提示**：`workbench doctor` 现在会报告用户级 MCP server 数量，
   并提示直接 `claude` 会话会加载全部 schema、而工作台启动器默认隔离。
4. **回归测试**：启动器 strict 标志、按需 `.mcp.json`、审计工具的分组/
   不泄漏/CLI 输出均有离线契约。

## 当前机器的立即恢复步骤

全局配置不在本次自动修改权限内，需要用户自己执行（执行前确认不再需要
REA 常驻）：

```bash
claude mcp remove rea -s user
claude mcp remove scrapling -s user   # 可选：不需要抓取时
```

然后**退出并重启** Claude Code（工具 schema 在启动时加载，`/clear` 不够），
用工作台启动器启动：

```bash
python tools/workbench.py --target <workbench> launch --run
```

验证：

```bash
python tools/context_audit.py --cwd <project>
```

期望：`request tools` 不再包含 `mcp__rea__*`；若仍需要 REA，只为单次会话
提供 `--mcp-config`，并接受其 207 个工具的常驻成本，不要全局常开。

## 已验证 / 仍待验证

**测量口径**：259 工具来自交互事故会话（Claude Code 2.1.303）；
0 个 MCP 工具来自独立的 headless probe（同一 2.1.303，但不同运行模式、
不同原生工具数）。两者不是同一个 run，不能把差值直接当成交互会话的
Token 节省百分比。

- **T3 headless probe（已验证，范围有限）**：在临时空项目安装工作台并执行真实
  启动器，`--print` 请求只剩 **22 个原生工具、0 个 MCP 工具**，schema
  51,264 字符（~12,816 tokens，估算），压缩次数 0；对照事故会话的
  259 工具 / 896,681 字符 / 3 次自动压缩。T3 是 headless 模式，原生工具
  数量比交互模式少 6 个，因此只对比 MCP 工具与 schema 量，不把该探针的
  字符差直接宣称为端到端 Token 节省比例。
  该次真实调用的 usage 为 `input_tokens: 7014` +
  `cache_read_input_tokens: 14136`，`output_tokens: 10`，无压缩边界。
- **T1 UNVERIFIED**：没有构造一个完全独立的认证/配置环境；最小原生会话
  未单独测试。
- **长时间任务未复跑**：本次探针证明启动上下文已从 231 个 MCP 工具降到 0，
  但没有复跑原先那种数小时、多轮工具调用的完整业务任务。"长时间任务不再
  触发 autocompact" 仍需用户在实际工作中观察确认。
- 403 的最终处理取决于 Provider：Ark 兼容端点不提供 Anthropic 的
  server-side Web Search。需要联网时使用该 Provider 支持的搜索工具，或
  切换到支持 Web Search 的 Provider；不要在 403 上循环重试。
