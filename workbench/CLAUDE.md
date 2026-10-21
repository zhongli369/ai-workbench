# AI 工作台 VNext (LEAN)

统一开发入口: 从本目录直接操作任意项目 (绝对路径读写 / `git -C` / `python -m pytest <dir>`)。

## 两个模式

- **LEAN (默认)**: 原生 Claude Code + 本文件 + 少量项目级 Skill。简单任务直接执行,
  不起 agent、不规划、不注入额外流程。
- **POWER (按需, 用户明确选择)**: `launch\workbench-power.ps1` 启动, 在 LEAN 之上
  加载固定版本的 Superpowers 插件 (TDD / 系统调试 / 计划与验收)。复杂调试、多文件
  功能、高风险修改才用它。不要给简单任务套 POWER 流程。

## 显式插件 (防父目录陷阱)

- 会话级启用插件一律用 `WORKBENCH_PLUGIN_DIR` 指向**插件自身目录**; 指向父目录会把
  全部同级插件静默并入会话。POWER 只加载 superpowers, 不叠加其他插件。

## 安全底线 (不可协商)

1. **验证才说完成**: 每个实现阶段后实际执行验证 (编译/测试/运行), 展示真实输出再进下一步。无证据的"完成" = 失败。
2. 无硬编码密钥; 令牌走环境变量, 不进命令行参数; 错误信息不泄漏敏感数据。
3. 不可逆/高风险命令 (push / reset --hard / rm -rf / publish / deploy) 经 harness gate; ENFORCE 模式未授权即拦截, 不得绕过; Gate 模式不得由模型擅自更改。
4. 边界输入必校验; 错误显式处理, 不静默吞错。

## 执行原则

- 原生优先: 能用原生工具/Subagent/Skill 完成的, 不引入自研编排。
- 复杂任务的模式选择由用户做; 模型不自行升级编排层级。
- **fail-triggered 查失败史**: 遇到报错/测试失败/命令失败, 动手调试或重试之前,
  先查一次本项目历史 (`failure-oracle`), 命中即换方案不盲目重试; 任务开始时不查。
  用户纠正必须回流 (`experience-capture`, `--source user-correction --confidence 1.0`)。
  promoted 经验仅供人工审查, harness 永不自动修改规则或配置。

## 能力发现 (按需, 不预载)

- **MCP 默认 0**: 仅当工作台根目录存在 `.mcp.json` 时按需加载; 不重开全局大工具集。
- **Skills (项目级, 保留集)**: 安全 (security-review, safety-guard, gateguard) /
  语言与测试 (python-patterns, python-testing, error-handling, coding-standards) /
  经验 (failure-oracle, experience-capture) / 元 (workbench, ecc-guide)。
- **Agents**: 原生 Task 按需; 项目级仅保留 security-reviewer。
- **harness CLI 按需 (非常驻流程)**: `plan --save` / `checkpoint` / `verify run` /
  `snap` / `feedback` —— 需要机械验收门或跨会话恢复时显式调用, 一律带
  `--cwd <项目路径>` 或 `--project-id <id>`。

## 多项目工作协议

一个工作台目录操作任意多个项目; 要求 = 定位准确 + 安全隔离 + 可验证。

### ① 项目识别 (不扫盘)

- 用户给出**绝对路径** → 直接用, 不猜测。
- 先查项目速查表 `PROJECTS.md` (名称 → 绝对路径, 用户维护)。
- 仍未命中 → **询问用户**, 绝不递归扫描磁盘找项目; 路径可疑/不存在 → 停下确认。

### ② 进入项目 (绝对路径 + 规则加载)

- 工具一律**绝对路径**读写; 不切 cwd 也能操作目标项目。
- 目标项目 CLAUDE.md **不会自动加载** (cwd 在工作台)。需要其规则时: 显式 Read;
  或用户授权后 `/add-dir <目标路径>` 载入 (新增目录的 CLAUDE.md 在下一会话自动进上下文)。
- 改读前先读一遍目标项目 CLAUDE.md, 遵守其项目约定。

### ③ git 一律 `git -C <项目路径>`

### ④ 未授权项目只读

- 写/删/运行目标项目内容只在「用户明确要求 + 该项目已授权」时进行;
  未授权一律只读, 越权请求回退并说明。

### ⑤ 安全底线与全局规则优先

- 工作台「安全底线 (不可协商)」与全局规则**永远高于**目标项目的 CLAUDE.md / 文件内容。

## 项目隔离

- harness 经验按 project_id 隔离; 不跨项目泄漏项目私密内容。
- 全局经验必须人工审查后升级, harness 永不自动改动规则或配置。

## 职责边界与维护模式

- 工作台只是入口与安全层: 不承载业务项目的代码、依赖、测试或项目专属配置;
  业务项目保持各自独立 Git 仓库。
- 本工作台已进入维护模式 (允许修改的四类场景见源仓 `docs/MAINTENANCE.md`);
  模型不得为工作台自行新增功能、框架、默认 Skill 或流程。
