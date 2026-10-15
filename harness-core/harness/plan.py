"""Deterministic task planning — archetype classification + phase scaffolds.

TOTAL FUSION Batch 3: minimal extraction of CodeLike's planning core
(brain/planning/task_decompose.py + risk_analysis.py) into one stdlib-only
module. This is the DEEP-mode phase scaffold: a complex task gets classified
into one of 13 archetypes, mapped to an ordered phase list with per-phase
risk, plus acceptance criteria. Phases hang on Batch-1 checkpoints
(`harness checkpoint begin/save --stage <phase name>`), giving long-horizon
work a resumable spine.

Deliberately NOT migrated (with reasons, per audit 03/04 disposition):
  - feedback adaptation (_inject_feedback_warning, retention logging):
    the native failure oracle (feedback.py + fail-triggered query policy)
    covers cross-session failure memory; a second adaptation path would
    duplicate it (audit 07 D-class duplication).
  - entity/flow/sub-capability regex enrichment: decorative rewriting of
    phase descriptions; added 150+ lines of fragile heuristics for zero
    measured effect (CodeLike had 0 external pulls).
  - project_scan dependency: phases no longer branch on repo detection;
    the generic fallback is a fixed 4-phase scaffold.
  - prompt factory / evaluate(): CodeLike's raison d'être, not planning.

Zero LLM. Zero network. Deterministic: same task string → same plan.
"""

from __future__ import annotations

import re

SCHEMA_VERSION = 1

ARCHETYPES = (
    "bugfix", "refactor", "migration", "performance", "review", "testing",
    "design", "feature-ui", "feature-api", "feature-integration",
    "feature-config", "feature-data", "feature-generic",
)


# ---------------------------------------------------------------------------
# archetype classification (verbatim signal tables from CodeLike task_decompose)
# ---------------------------------------------------------------------------

def detect_task_type(task: str) -> str:
    """Detect task type from signal words. Order matters — specific before broad."""
    t = task.lower()

    if any(w in t for w in ("refactor", "reorganize", "restructure", "simplify",
                             "重构", "重组", "整理", "简化", "拆分")):
        return "refactor"
    if any(w in t for w in ("migrate to", "upgrade to", "port to", "update version",
                             "升级", "移植")):
        return "migration"
    # "迁移" alone is too broad — "添加迁移" = adding a migration file (feature-data)
    if "迁移" in t and not any(w in t for w in ("添加", "新增", "创建", "增加", "新建")):
        return "migration"
    if any(w in t for w in ("optimize", "performance", "speed up", "faster", "cache",
                             "优化", "加速", "提速", "性能", "缓存")):
        return "performance"

    if any(w in t for w in ("fix", "bug", "error", "broken", "crash", "issue",
                             "修复", "修正", "改正", "缺陷", "修好", "崩溃")):
        return "bugfix"

    if any(w in t for w in ("review", "audit", "inspect",
                             "审查", "审计", "检查")):
        return "review"

    if any(w in t for w in ("write test", "add test", "coverage", "unit test",
                             "写测试", "加测试", "覆盖率", "单元测试", "测试用例")):
        return "testing"

    if any(w in t for w in ("design", "architect", "architecture",
                             "设计", "架构")):
        return "design"

    if any(w in t for w in ("add", "create", "implement", "build", "make",
                             "new", "introduce", "flag", "support", "feature",
                             "添加", "新增", "增加", "创建", "实现", "构建",
                             "引入", "支持", "功能", "开发")):
        return _detect_feature_subtype(task)

    return _detect_feature_subtype(task)


def _detect_feature_subtype(task: str) -> str:
    """Classify feature tasks into sub-types. Only called for feature-type tasks."""
    t = task.lower()

    if any(w in t for w in (
        "button", "form", "modal", "page", "component", "layout", "style",
        "css", "scss", "ui ", "frontend", "view", "screen", "display",
        "render", "interface", "dialog", "toast", "notification ui",
        "nav", "menu", "sidebar", "header", "footer", "dashboard",
        "widget", "icon", "animation", "responsive",
        "按钮", "表单", "弹窗", "页面", "组件", "布局", "样式",
        "界面", "前端", "视图", "显示", "渲染", "导航", "菜单",
        "侧边栏", "页眉", "仪表盘", "对话框", "图标", "动画",
        "响应式", "移动端", "适配",
    )):
        return "feature-ui"

    # Integration / External (check BEFORE API — "对接...服务" is integration)
    if any(w in t for w in (
        "connect", "integrate", "webhook", "sync", "import", "export",
        "third-party", "external", "oauth", "sso", "ldap", "payment",
        "gateway", "adapter", "plugin", "extension", "sdk",
        "连接", "集成", "同步", "导入", "导出", "第三方", "外部",
        "支付", "网关", "适配器", "插件", "扩展", "对接", "打通",
    )):
        return "feature-integration"

    if any(w in t for w in (
        "endpoint", "route", "handler", "controller", "middleware",
        "api", "rest", "graphql", "grpc", "backend", "server",
        "service", "request", "response", "json", "status code",
        "接口", "路由", "中间件", "后端", "服务", "请求", "响应",
        "控制器", "端点", "api",
    )):
        return "feature-api"

    if any(w in t for w in (
        "config", "env", "setting", "flag", "toggle", "feature-flag",
        "environment", "variable", "parameter", "option", "preference",
        "constant", "dotenv", "properties",
        "配置", "设置", "环境变量", "参数", "选项", "开关",
        "常量",
    )):
        return "feature-config"

    if any(w in t for w in (
        "model", "schema", "migration", "database", "table", "query",
        "seed", "fixture", "orm", "entity", "repository", "datastore",
        "column", "index", "relation", "field", "sql",
        "模型", "数据表", "数据库", "查询", "字段", "索引", "存储",
        "实体", "数据结构",
    )):
        return "feature-data"

    return "feature-generic"


# ---------------------------------------------------------------------------
# phase templates (verbatim from CodeLike task_decompose.decompose)
# ---------------------------------------------------------------------------

_PHASE_TEMPLATES: dict[str, list[dict]] = {
    "bugfix": [
        {"name": "Reproduce & Locate", "description": "Reproduce the bug. Read error messages/logs. Locate the exact file and line causing the issue. Understand the code path leading to the failure."},
        {"name": "Fix", "description": "Implement the minimal fix. Change only what's needed to resolve the root cause. No refactoring or feature additions."},
        {"name": "Verify", "description": "Confirm the bug is fixed. Run relevant tests. Check for regressions in related functionality."},
    ],
    "refactor": [
        {"name": "Map Current Structure", "description": "Document the current code structure. Identify all files, imports, and references that will be affected. List the target structure."},
        {"name": "Apply Changes", "description": "Move/rename/extract code as planned. Update all imports and references. No behavior changes."},
        {"name": "Verify Integrity", "description": "Run full test suite. Confirm no behavior change. Verify all imports resolve. Check build succeeds."},
    ],
    "review": [
        {"name": "Deep Review", "description": "Read target code thoroughly. Check: correctness, security, error handling, performance, conventions. Note file:line for each finding."},
        {"name": "Report", "description": "Document findings classified by severity: CRITICAL / HIGH / MEDIUM / LOW. Include specific file:line references and suggested fixes."},
    ],
    "testing": [
        {"name": "Plan Test Coverage", "description": "Map existing code paths. Identify untested functions/branches. Prioritize by risk. Choose test approach for each."},
        {"name": "Write Tests", "description": "Implement tests following AAA pattern. Cover happy path, edge cases, and error cases. Use existing test framework."},
        {"name": "Run & Verify", "description": "Run all tests. Confirm passing. Check coverage. Verify no regressions."},
    ],
    "design": [
        {"name": "Research Existing", "description": "Survey current architecture. Read key files. Identify constraints and integration points. Note patterns already in use."},
        {"name": "Design Solution", "description": "Propose architecture. Define components, interfaces, data flow. Consider alternatives. Write ADR if significant."},
        {"name": "Document & Plan", "description": "Write architecture document with ASCII diagrams. Break into implementation phases. List risks and mitigations."},
    ],
    "migration": [
        {"name": "Assess Impact", "description": "Identify all affected files, dependencies, and APIs. Read breaking changes documentation. Create migration checklist."},
        {"name": "Migrate", "description": "Apply changes systematically. Update configs, imports, API calls. Follow official migration guide. Document decisions."},
        {"name": "Verify", "description": "Run full test suite. Check build succeeds. Verify no regressions. Test deployment if applicable."},
    ],
    "performance": [
        {"name": "Profile", "description": "Identify bottlenecks. Measure current performance. Find the hot path. Quantify the problem with numbers."},
        {"name": "Optimize", "description": "Apply targeted optimization. Focus on the bottleneck. Avoid premature optimization. Keep code readable."},
        {"name": "Benchmark", "description": "Measure improvement. Compare before/after. Verify no correctness regressions. Document results."},
    ],
    "feature-ui": [
        {"name": "Design Component", "description": "Define the UI component structure. Identify existing design patterns and reusable components. Sketch the visual layout and interaction states (loading, empty, error, success)."},
        {"name": "Implement UI", "description": "Build the UI component following existing design conventions. Handle all states: loading, empty, error, edge cases. Keep styling consistent with the project's design system."},
        {"name": "Visual Verify", "description": "Confirm the UI renders correctly. Test all interaction states. Verify responsive behavior on target screen sizes. Check accessibility (keyboard nav, screen reader)."},
    ],
    "feature-api": [
        {"name": "Design Endpoint", "description": "Define the API contract: method, path, request/response schema, error codes. Check existing route patterns and follow them exactly. Document the interface before implementing."},
        {"name": "Implement Handler", "description": "Build the route handler with input validation, business logic, and error handling. Follow existing middleware patterns. Keep handler focused — extract complex logic to service functions."},
        {"name": "Test Endpoint", "description": "Test happy path, invalid input, auth failure, and edge cases. Verify status codes match the contract. Confirm existing endpoints are unaffected."},
        {"name": "Document", "description": "Add API documentation if the project has API docs. Update any client SDK or type definitions. Note any rate limiting or quota considerations."},
    ],
    "feature-integration": [
        {"name": "Research External API", "description": "Read the third-party API documentation thoroughly. Understand auth method, rate limits, error responses, and data format. Identify the minimal set of API calls needed."},
        {"name": "Design Adapter", "description": "Design an adapter that wraps the external API. Define clean internal interfaces — the rest of the codebase should not depend on the third-party API directly. Plan error handling and retry logic."},
        {"name": "Implement Adapter", "description": "Build the adapter following the project's existing adapter/connector patterns. Handle auth, request formatting, response parsing, and errors. Add logging for all external calls."},
        {"name": "Integration Test", "description": "Test with real API if possible, or mock with recorded responses. Verify error handling works (timeout, auth failure, rate limit). Confirm the adapter works end-to-end."},
    ],
    "feature-config": [
        {"name": "Identify Scope", "description": "List all files and modules that need the new config. Check existing config patterns (.env, config.py, app settings). Define default values and validation rules."},
        {"name": "Implement Config", "description": "Add the config following existing patterns exactly. Provide sensible defaults. Add validation at startup. Document what each config controls."},
        {"name": "Verify Defaults", "description": "Confirm the system works correctly with default config values. Test with overridden values. Verify config errors are caught at startup with clear messages."},
    ],
    "feature-data": [
        {"name": "Design Schema", "description": "Define the data model: fields, types, constraints, relationships. Check existing schema patterns and naming conventions. Consider migration path if modifying existing schema."},
        {"name": "Implement Schema", "description": "Create migration or schema definition. Add seed data or fixtures if needed. Update any ORM models or type definitions. Follow existing data access patterns."},
        {"name": "Verify Data", "description": "Run migrations and verify schema is correct. Test CRUD operations. Check data integrity constraints. Verify queries perform as expected."},
    ],
}

_GENERIC_PHASES = [
    {"name": "Understand", "description": "Read existing code to understand current state. Identify what exists and what needs to be added."},
    {"name": "Design", "description": "Plan the implementation. Identify files to create/modify. Define interfaces and data flow."},
    {"name": "Implement", "description": "Build the feature. Follow existing conventions. Keep changes focused and minimal."},
    {"name": "Verify", "description": "Test the implementation. Run the code. Confirm it works."},
]


# ---------------------------------------------------------------------------
# per-phase risk (static base from CodeLike risk_analysis; adaptive history /
# hot-files inputs dropped — they required the retired feedback-store coupling)
# ---------------------------------------------------------------------------

def _base_risk(phase_name: str, task_type: str) -> tuple[str, str]:
    if task_type == "bugfix":
        if "Fix" in phase_name:
            return ("LOW", "localized fix — minimal change, bounded scope")
        if "Verify" in phase_name:
            return ("MEDIUM", "verification — may surface regressions in related code")
        return ("LOW", "bugfix phase — bounded risk")
    if task_type == "refactor":
        if "Apply" in phase_name:
            return ("MEDIUM", "spread imports and references — potential breakage across files")
        if "Verify" in phase_name:
            return ("MEDIUM", "verification — test suite may reveal missed references")
        return ("LOW", "mapping/planning — read-only analysis")
    if task_type == "review":
        return ("LOW", "read-only — no code changes, findings only")
    if task_type == "testing":
        if "Run" in phase_name or "Verify" in phase_name:
            return ("MEDIUM", "running tests may surface existing regressions")
        return ("LOW", "test authoring — additive only, no production code changes")
    if task_type == "design":
        return ("LOW", "read-only analysis and documentation — no code changes")
    if task_type == "migration":
        if "Migrate" in phase_name:
            return ("HIGH", "breaking changes and dependency updates — high blast radius")
        if "Assess" in phase_name:
            return ("MEDIUM", "identifying affected files — may miss implicit dependencies")
        return ("MEDIUM", "verification — breaking changes may surface in unexpected places")
    if task_type == "performance":
        if "Optimize" in phase_name:
            return ("MEDIUM", "optimization can introduce subtle correctness bugs")
        if "Benchmark" in phase_name:
            return ("MEDIUM", "benchmark results — correctness must be verified")
        return ("LOW", "profiling — measurement only, no code changes")
    if task_type == "feature-ui":
        if "Implement" in phase_name:
            return ("MEDIUM", "UI changes — visual regression risk across screen sizes")
        if "Verify" in phase_name:
            return ("MEDIUM", "visual verification — may surface styling regressions")
        return ("LOW", "UI design — read-only planning")
    if task_type == "feature-api":
        if "Implement" in phase_name:
            return ("MEDIUM", "API changes — contract and backward compatibility risk")
        if "Test" in phase_name:
            return ("MEDIUM", "API testing — may surface contract mismatches")
        if "Document" in phase_name:
            return ("LOW", "documentation — no code changes")
        return ("LOW", "API design — read-only planning")
    if task_type == "feature-integration":
        if "Implement" in phase_name:
            return ("HIGH", "external integration — dependency on third-party API behavior")
        if "Research" in phase_name:
            return ("LOW", "research — read-only, no code changes")
        if "Test" in phase_name:
            return ("MEDIUM", "integration testing — may require external service access")
        return ("MEDIUM", "integration work — external dependency risk")
    if task_type in ("feature-config", "feature-data"):
        if "Implement" in phase_name:
            return ("MEDIUM", "schema/config changes — may affect existing data or behavior")
        if "Verify" in phase_name:
            return ("MEDIUM", "verification — check defaults and existing data integrity")
        return ("LOW", "planning — read-only design")
    if "Design" in phase_name:
        return ("MEDIUM", "planning — decisions made here affect all later phases")
    if "Implement" in phase_name:
        return ("MEDIUM", "code changes — bounded scope but correctness risk")
    if "Test" in phase_name or "Verify" in phase_name:
        return ("MEDIUM", "verification — may surface implementation gaps")
    return ("LOW", "understanding/research — read-only")


def risk_for_phase(phase_name: str, task_type: str,
                   phase_num: int) -> tuple[str, str]:
    """Static risk for a phase. Phase 1 is always LOW (read-only research)."""
    if phase_num == 1:
        return ("LOW", "initial research — read-only, no code changes")
    return _base_risk(phase_name, task_type)


# ---------------------------------------------------------------------------
# acceptance criteria (verbatim from CodeLike ARCHETYPE_AC_TEMPLATES)
# ---------------------------------------------------------------------------

ARCHETYPE_AC_TEMPLATES: dict[str, list[str]] = {
    "bugfix": [
        "Bug no longer reproduces under the original reproduction steps",
        "Root cause is identified and fixed (not just symptoms)",
        "Existing tests all pass — no regressions introduced",
        "The specific error/log message that led to discovery is gone",
    ],
    "refactor": [
        "All existing tests pass with zero changes to test code",
        "Behavior is identical — no observable change to users",
        "All imports resolve correctly after restructuring",
        "Build succeeds with no new warnings",
    ],
    "review": [
        "All findings include specific file:line references",
        "Each finding is classified by severity (CRITICAL/HIGH/MEDIUM/LOW)",
        "Suggested fixes are provided for CRITICAL and HIGH findings",
    ],
    "testing": [
        "New tests cover happy path, edge cases, and error cases",
        "Tests follow existing test framework and naming conventions",
        "Coverage on new/changed code meets project threshold (or 80%+)",
        "All existing tests still pass",
    ],
    "design": [
        "Architecture document includes component diagram (ASCII or inline)",
        "Interfaces between components are explicitly defined",
        "At least one alternative considered with trade-off analysis",
        "Implementation plan is broken into discrete, ordered phases",
    ],
    "migration": [
        "All affected files identified and updated",
        "Build succeeds with new dependency versions",
        "Full test suite passes with no regressions",
        "Breaking changes documented in migration notes",
    ],
    "performance": [
        "Before and after benchmark numbers are recorded",
        "Performance improvement is quantified (e.g., 'p99 from 200ms to 45ms')",
        "Correctness is verified — no behavior changes",
        "Optimization is focused on the actual bottleneck (not guessed)",
    ],
    "feature-ui": [
        "Component renders correctly at target screen sizes",
        "All interaction states work: loading, empty, error, success",
        "Styling is consistent with existing design system",
        "Keyboard navigation and basic accessibility work",
    ],
    "feature-api": [
        "Endpoint returns correct status code and body for happy path",
        "Invalid input returns appropriate error response",
        "Auth/permission checks work correctly",
        "Existing endpoints are unaffected",
    ],
    "feature-integration": [
        "External API calls succeed with correct auth and request format",
        "Error handling covers: timeout, auth failure, rate limit, bad response",
        "Adapter has clean internal interface — rest of codebase doesn't depend on external API directly",
        "All external calls are logged (request, response, latency)",
    ],
    "feature-config": [
        "System works correctly with default config values",
        "Invalid config values produce clear error messages at startup",
        "Config change takes effect without code changes (env var or config file)",
        "Config is documented: name, type, default, valid values, effect",
    ],
    "feature-data": [
        "Migration runs forward and rollback without errors",
        "CRUD operations work correctly on the new schema",
        "Data integrity constraints are enforced (unique, not null, foreign key)",
        "Existing data is preserved and accessible after migration",
    ],
    "feature-generic": [
        "The feature works as described in the task",
        "Existing functionality is preserved — no regressions",
        "Code follows existing project conventions",
        "Tests exist for the new functionality",
    ],
}


# ---------------------------------------------------------------------------
# public entry
# ---------------------------------------------------------------------------

def slugify(task: str, maxlen: int = 40) -> str:
    """Stable execution-id slug from a task string (ASCII, filesystem-safe)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", task.lower()).strip("-")
    return slug[:maxlen].strip("-") or "task"


def plan(task: str, archetype: str | None = None) -> dict:
    """Task → plan dict. Deterministic: same input, same output.

    The returned phases double as checkpoint stage names for DEEP-mode
    long-horizon work (harness checkpoint begin/save --stage <name>).
    """
    if not task or not task.strip():
        raise ValueError("task must be a non-empty string")
    task_type = archetype or detect_task_type(task)
    if task_type not in ARCHETYPES and task_type != "feature":
        raise ValueError(f"unknown archetype: {task_type!r} (one of {list(ARCHETYPES)})")
    if task_type == "feature":
        task_type = "feature-generic"
    template = _PHASE_TEMPLATES.get(task_type) or _GENERIC_PHASES
    total = len(template)
    phases = []
    for i, p in enumerate(template):
        risk, reason = risk_for_phase(p["name"], task_type, i + 1)
        phases.append({"num": i + 1, "name": p["name"],
                       "description": p["description"],
                       "risk": risk, "risk_reason": reason})
    return {
        "schema": SCHEMA_VERSION,
        "task": task,
        "archetype": task_type,
        "phases": phases,
        "acceptance_criteria": list(ARCHETYPE_AC_TEMPLATES.get(
            task_type, ARCHETYPE_AC_TEMPLATES["feature-generic"])),
        "checkpoint_hint": {
            "execution_id": slugify(task),
            "stages": [p["name"] for p in phases],
            "note": ("DEEP mode: harness checkpoint begin/save --exec "
                     f"{slugify(task)} --stage <stage> per phase; verify with "
                     "harness checkpoint verify"),
        },
    }
