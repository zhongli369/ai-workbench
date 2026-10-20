# 维护模式说明（R7.1, 2026-10-20 起生效）

AI Workbench 自 R7.1 起进入**维护模式（冻结功能扩张）**。

## 允许修改的场景（仅此四类）

1. 真实安全缺陷。
2. Claude Code 上游升级导致兼容性失效。
3. 已确认的功能故障。
4. 多个真实项目反复出现、原生能力与成熟插件均无法解决的通用能力缺口。

## 冻结期内不做

- 不添加 Agent 框架 / 自动规划系统 / 默认 Skills。
- 不为启动 Token 或版本数字做优化性开发。
- 不在无实际需求时运行大型付费 benchmark。
- 不重复 R1–R7 已完成的审计。

## 开源插件升级原则

需要时检查 → 隔离验证（stream-json init 探针 + 八点核查，见
`docs/open-source-adoption.md`）→ 确认收益后采用。

## 搁置候选登记

| 候选 | 状态 |
|---|---|
| r6-slim @1b91f1c（R6 极简 CLAUDE.md，10 skills） | **可选实验候选，未证明净收益，默认不启用。** 不合并、不部署、不删除；无模型级对照证据前其指令更改不得进入 main。 |

## 已知边界（非缺陷，维护时须知）

- 安装器漂移保护（R7.1 起）：受管文件被本地修改后重装会备份为 `<file>.user-bak`
  再刷新为 canonical；旧清单（无 hashes）首次重装 fail-open 一次。
- capability 接线改写的文件不参与漂移哈希记录，重装可能为其产生冗余
  `.user-bak`（fail-safe 方向，不丢数据）。
- 卸载（owns-only sweep）不识别漂移，受管文件会被删除——卸载即销毁语义，
  需要保留先自行备份。
- `test_powershell_launcher_keeps_positional_args_after_mcp_config` 在本机
  代码页环境下失败（pristine main 复验，与代码无关）。
