---
name: workbench
description: AI 工作台跨项目操作模式: 从工作台目录直接读写/测试/git 其他项目,项目状态隔离,目标项目规则如何加载,经验按 project_id 隔离。
origin: harness-core
---

# Workbench — 跨项目操作手册

## 模型

工作台目录 (`workbench-vnext/`) 是唯一启动入口;目标项目 = 任意其他目录。
不切换 cwd 也能操作: 工具用绝对路径,git 用 `git -C <dir>`,pytest 用 `python -m pytest <dir>`。

## 目标项目规则加载

- 目标项目的 CLAUDE.md **不会自动加载** (cwd 在工作台)
- 需要时: 显式 Read 目标项目 CLAUDE.md,或 `/add-dir <目标目录>` 授权工具作用域
- env `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` 可开启附加目录 CLAUDE.md 自动加载
  (工作台 settings 已设;首次使用某项目时仍建议显式确认其规则)

## 状态隔离铁律

- harness 经验按 project_id 隔离: 目标项目根放 `.harness-project` 文件 (一行 id) 可固定身份
- 不把 A 项目的经验/规则写进 B 项目;全局经验必须人工审查后升级
- CC 自带 memory 按项目 keyed,天然隔离 — 不跨项目引用 memory 内容

## 操作速查

| 需求 | 做法 |
|---|---|
| 改目标项目代码 | 绝对路径 Read/Edit,改前 Read 目标 CLAUDE.md |
| 跑目标项目测试 | `python -m pytest F:/path/to/proj/tests -q` |
| 目标项目 git | `git -C F:/path status` (commit 需用户要求) |
| 查目标项目失败史 | 在目标目录跑 failure-oracle 命令,或 `--project-id` 显式指定 |
| 高风险命令 | gate ENFORCE 模式会拦截,需人工 `gate approve` |
