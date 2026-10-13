---
name: failure-oracle
description: 重试失败方案、遇到报错、或不熟悉的任务前,先查本项目历史失败原因。避免盲目重试已知失败路径。harness-core 提供,JSONL 本地存储,零网络。
origin: harness-core
---

# Failure Oracle — 失败史按需检索

## 何时用 (fail-triggered, 不默认每任务先查)

- 遇到报错 / 测试失败 / 命令失败, 准备调试或重试**之前** — 先查一次本项目历史
- 准备重试一个已知失败过的方案/命令/库
- 用户明确要求查历史

实测教训 (fb-b26968ccc336): 新鲜单缺陷任务**默认先查** oracle 会使成本 ~2x 且质量无增益。
失败路径才查 ≠ 默认先查: 顺利路径零开销, 只有真正遇到失败时才付费查询。

## 命令 (在目标项目目录或有 .harness-project 的目录下执行)

```bash
python harness-core/harness/cli.py feedback query --keyword "<关键词>" --json
python harness-core/harness/cli.py feedback query --last 5
python harness-core/harness/cli.py feedback stats
python harness-core/harness/cli.py report
```

- `--keyword` 对 summary+cause 做大小写不敏感子串匹配 — 报错信息摘一段即可
- `report` 输出复发模式 (同一 cause ≥2 次) + 升级候选
- project_id 自动解析 (.harness-project 文件 > git remote 去凭据 > 路径哈希)

## 铁律

- 命中历史失败 → 换方案或先解决根因,不要用相同参数重试
- 未命中 → 正常执行;失败后用 experience-capture 回流
- 查询按时间倒序返回 (实现无 source 加权); 解读时人工按 source 权威性递减采信: user-correction > human-verified > model-inference > experiment-seed (合成夹具, 永远不得 promote 为生产证据)
