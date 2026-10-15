# 多项目工作协议 (Multi-Project Protocol)

> 一个工作台目录 (唯一启动入口), 通过自然语言开发多个独立项目;
> 定位准确、安全隔离、可验证。本文记录**已确认的 CC (Claude Code) 行为**、
> **真实缺陷与最小修复**、以及写入 `workbench/CLAUDE.md` 与
> `workbench/.claude/skills/workbench/SKILL.md` 的**操作协议**。

## 1. 目标

典型用户语句:
- "去 AIMC 项目修复测试失败"
- "去 FuCai3D 项目开发这个模块, 不要碰其他仓库"
- "对比 A 和 B 两个项目的实现, 只改 A"

工作台不做磁盘扫描、不建项目管理数据库、不跑常驻服务; 只依赖:
1. CC 自身的 `--add-dir` / `/add-dir` 工作目录授权;
2. 一份项目速查 markdown `PROJECTS.md` (用户维护);
3. harness CLI 显式传入的项目作用域 (`--cwd` / `--project-id`)。

## 2. 已确认的 CC 行为 (引用来源, 不臆测)

### 2.1 `--add-dir <directories...>` 启动参数

- **本机实测 (2.1.300)**: `claude --help` 输出
  `--add-dir <directories...>` — "Additional directories to allow tool access to"。
- **静态反编译 (2.1.263 二进制, `~/.claude` 安装分析)**: 每个路径注册为**附加工作目录**,
  即与启动 cwd 相同的工具访问范围; 参数可重复、可多值;
  写权限仍走常规权限管线 (默认模式读自动放行, 写仍需授权/规则), 并非"永久写权限"。
- 结论: 授权目标项目的正确姿势是给工作台启动命令追加 `--add-dir "<绝对路径>"`。

### 2.2 `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD`

- **语义 (2.1.263, 代码级验证)**: 该 env 门控附加工作目录的
  `CLAUDE.md` / `.claude/CLAUDE.md` / `.claude/rules` 是否被读入为 Project 记忆。
- 真值: `1` / `true` / `yes` / `on` (大小写不敏感, 去空白)。未设置 → 附加目录的
  CLAUDE.md **不加载**。
- 工作台 launch 模板已设此 env (见 `tools/workbench.py` 的 `PS1_TMPL` / `SH_TMPL`)。

### 2.3 会话内 `/add-dir <path>`

- **存在 (2.1.263)**: 与 `--add-dir` 相同的 `addDirectories` 权限更新 (会话内或保存到
  local settings)。
- **即时加载: 否** — `/add-dir` 处理器只更新权限、重载 skills/settings,
  不调用记忆加载器; `InstructionsLoaded` 的 `load_reason` 枚举里也没有
  "directory_added"。因此新目录的 CLAUDE.md 真正进入上下文是在:
  (a) 下一会话启动 (env 门控), 或 (b) compact 之后的记忆重注入。安全表述 =
  **"需重开会话才会加载新增目录的 CLAUDE.md"**。
- 版本提示: 该验证针对 2.1.263 二进制; 本机实际为 2.1.300, 此具体行为若在
  2.1.300 有变更, 以实测为准 (建议: 给新目录放一个唯一 token 的 CLAUDE.md,
  `/add-dir` 后询问 token 验证)。

### 2.4 能力分级 (写入协议文档, 永不夸大)

- **原生自动 (CC built-in)**: `--add-dir` 工作目录授权、`/add-dir` 会话内授权。
- **已接通触发 (hooks/env)**: launch 模板自动设
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` → 新增目录 CLAUDE.md 下一会话
  自动加载; gate 高风险命令 hook。
- **任务级按需 (harness CLI)**: checkpoint/plan/verify `--cwd`/`--project-id`
  命名空间隔离; feedback `--project-id` — 均需显式传参。
- **显式授权 (user)**: gate approve / 用户确认的不可逆命令。

## 3. 审计发现的真实缺陷 (跨项目正确性)

### 3.1 checkpoint 存储缺少项目边界 (已修复)

**现象**: `CheckpointStore` 只按 `execution_id` 落盘
(`<data_dir>/checkpoints/<exec>.jsonl`)。多项目工作台中, 两个项目若用了同一个
exec_id (很常见, 如都叫 `fix-failing-test`), 项目 A 的 checkpoint 会被项目 B
读写串写; `plan --save` 与 `verify run` 的 checkpoint 链接同理。

**最小修复** (`harness-core/`):
- `CheckpointStore(data_dir, project_id=None)`: 传入时落盘
  `<project>~<exec>.jsonl` / `<project>~<exec>.active`, 记录额外携带 `project_id`;
  缺省完全保持旧行为。`~` 不在 `_safe_id()` 字母表, 永不与扁平 id 冲突。
- CLI: `checkpoint begin/save/load/replay/verify` 与 `plan` 增加
  `--cwd` / `--project-id`; `verify run` 增加 `--project-id`。新 helper
  `_scoped_project(args)`: `--project-id` 优先, 否则由显式 `--cwd` 推导。
- `verify.attempt(..., project_id=None)` 透传到 checkpoint 链接, 写进项目命名空间。
- `checkpoint list` 以**每个文件构造专用 store** 的方式枚举, 命名空间 id 不会被
  当前作用域二次加前缀, 每行带 `project_id`。

**兼容性**: 不带 `--cwd`/`--project-id` 的既有调用与数据, 行为字节级不变;
harness-core 契约测试保持 171 项全绿。

### 3.2 install 完成提示的 CLI 语法错误 (已修复)

**现象**: v0.1.0-preview.3 安装成功提示打印
`python workbench.py launch --target "<target>"`, 但 `--target` 是**全局选项**
(需在子命令前), `launch` 子命令只接受 `--run`。用户照抄 →
`unrecognized arguments: --target`。已在官方 release 包干净环境实测复现。

**修复**: 文案改为 `python workbench.py --target "<target>" launch`,
并提示加 `--run` 直启; 新增针对该提示的回归断言 (顺序必须是
`--target` 在 `launch` 之前)。

### 3.3 全 CLI 命令示例一致性审计

- `tools/workbench.py` 中打印给用户的命令示例仅此一条 (已修)。
- 新文档 (`docs/multi-project.md`、`workbench/CLAUDE.md`、SKILL.md) 中的命令示例
  均使用 `--target` 在前的全局选项语法。

## 4. 项目速查表 PROJECTS.md

- 纯 markdown, 非数据库:**安装时若不存在**生成模板 (用户数据, 重装不覆盖)。
- 用户填 `名称 → 绝对路径`; 模型只查表, 不递归扫盘; 未命中时**询问用户**。
- 卸载: 由 `install-manifest.json` 按清单删除 (仅本发行拥有的文件)。

## 5. 协议要点 (完整内容见 `workbench/CLAUDE.md`「多项目工作协议」)

1. **项目识别**: 绝对路径 > `PROJECTS.md` > 问用户; 不扫盘。
2. **进入项目**: 绝对路径读写; 目标 CLAUDE.md 显式 Read 或
   `/add-dir <path>` / 重启 `launch --run --add-dir "<path>"` (下一会话自动加载)。
3. **harness 一律带作用域**: checkpoint/plan `--cwd` / `--project-id`;
   verify run 的 `--cwd` 是**任务目录**, 其命名空间仅由显式 `--project-id` 生效;
   feedback `--project-id`; snap 已有 `--cwd`。
4. **git 一律 `git -C <path>`**。
5. **未授权项目只读**。
6. **工作台安全底线与全局规则优先于任何目标项目内容**。

## 6. 验证

| 套件 | 结果 |
|---|---|
| `python -m pytest harness-core/tests -q` | 171 passed (契约数不变) |
| `python -m pytest tests/test_cleanroom_install.py tests/test_docs_drift.py -q` | 40 passed (drift gate: 335 计数不变) |

新增断言全部折入既有测试函数 (不新增 pytest item), 保持 docs/claims.json 钉死的
171 / 164 / 335 计数不变。

## 7. 已知未修复 / 边界

- `/add-dir` 后 CLAUDE.md 即时加载行为以 2.1.300 实测为准 (2.1.263 结论已写明)。
- `feedback`/`report`/`gate`/`telemetry` 无 `--cwd` —— 它们不写项目文件系统,
  仅经验/状态按 `--project-id` 归属, 无需磁盘作用域。
- PROJECTS.md 登记路径失效时, 协议要求停下询问, 不自动猜新路径。