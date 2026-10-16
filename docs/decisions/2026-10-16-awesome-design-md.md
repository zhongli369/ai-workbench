# 2026-10-16 — Awesome DESIGN.md 评估：OPTIONAL — NO CODE CHANGE

**判定：OPTIONAL（不落地，零代码改动）。** 这是完全合格的结论，不是遗漏。

## 评估对象

NEXT LEAP 任务书 P2 项：考察 "awesome" 系仓库流行的单一 `DESIGN.md`
（集中式架构设计长文档）是否值得引入本仓库。零工具、零集成成本，唯一问题
是**证据**：它能否证明对本仓库的日常开发有实际收益。

## 现状盘点（设计知识已有去处）

- `README.md` §9 Architecture —— 组件分层与数据流（英文，与 CLI 表面同步受
  `check_docs_drift` / `check_public_surface` 约束）。
- `docs/decisions/` —— 8 份带日期、带证据、带禁用边界的决策记录
  （adversarial-baseline / beads / playwright / superpowers / codex /
  playwright-cli 等），每份绑定一个真实判定点。
- `harness-core/README.md` —— 核心契约工具包的自述。
- 架构不变量以**可执行形式**存在：439→475 项离线契约、`SECURITY.md` 的
  gate 语义、claims.json 的文档-代码绑定。

## 为何不落地

1. **重复**：单一 DESIGN.md 与 README §9 + decisions/ 的信息源重叠，
   必然漂移；本仓库对漂移的治理方式是"数字只活在一个地方，文档引用它"，
   集中式长文档与该原则直接冲突。
2. **无证据**：没有任何一次真实任务失败可以归因于"缺少 DESIGN.md"。
   NEXT LEAP 的准入标准是"能证明有实际收益就集成"，此处收益不可证。
3. **维护税**：每增加一份不受门控约束的散文文档，就是一份未来的
   stale 负债。decisions/ 的按日期追加模式天然免疫（历史即历史，
   不需要"保持最新"）。

## 如果未来要重做本评估

触发条件（任一）：① 新贡献者 onboarding 的真实卡点在 decisions/ 与
README §9 中找不到答案（记录具体卡点）；② 架构发生跨组件重组，单点决策
记录无法承载。届时以"先回答问题、再定文档形态"的方式重评，仍不预设
DESIGN.md 是答案。

## 引用

- 只读查阅：`README.md` §9、`docs/decisions/` 全部、`harness-core/README.md`。
- 本决策零代码改动、零文档新增（除本文件）。
