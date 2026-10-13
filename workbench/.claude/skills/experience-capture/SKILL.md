---
name: experience-capture
description: 任务失败、用户纠正、或验证出意外事实时,把经验写入项目级失败史。来源与置信度明确,经验可升级/撤销,绝不自动注入全局规则。harness-core 提供。
origin: harness-core
---

# Experience Capture — 经验回流与升级

## 何时记录 (只记有用的)

- 任务执行失败,且原因对未来有价值 (非一次性环境问题)
- **用户明确纠正了模型** — 必须记,`--source user-correction --confidence 1.0`
- 验证推翻了模型的假设 (如"以为该 API 支持 X,实测不支持")
- 同一问题第二次发生 (复发信号,升级候选)

不记: 一次性网络抖动、已修复且无复发风险的小错、含私密信息的内容。

## 命令

```bash
H=harness-core/harness/cli.py  # 相对工作台根目录
python $H feedback record --cause <snake_case原因> --summary "<200字内: 什么失败+根因+正确做法>" \
  --source user-correction --confidence 1.0 --redact
python $H feedback promote --record-id <fb-xxx> --status verified    # 人工验证后
python $H feedback promote --record-id <fb-xxx> --status promoted    # 升级为规则候选
python $H feedback promote --record-id <fb-xxx> --status retired     # 撤销过期经验
python $H report                                                      # 复发模式 -> 升级建议
```

## 语义

- `candidate`(默认)→ `verified`(人工确认过) → `promoted`(可提炼为规则/Skill 的候选)
- promoted 只进入 `report` 输出供人工审查,**harness 从不自动修改任何规则或配置**
- 私密内容用 `--redact` (email/key 形状自动脱敏); 项目私密经验留在项目 project_id 下,不进全局

## 闭环验证

记录经验后,下次相关任务先用 failure-oracle 查询;若经验帮助避免了重复失败,
把该记录 promote 为 verified — 这是经验"真正影响后续任务"的证据链。
