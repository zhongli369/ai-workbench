"""Planning contracts (TOTAL FUSION Batch 3 — minimal CodeLike extraction).

Pins the migrated surface: 13-archetype bilingual classifier, phase
templates, per-phase static risk, per-archetype AC, determinism, the
documented classification traps ("添加迁移" ≠ migration; integration beats
API), checkpoint wiring via --save, and zero legacy-repo dependency.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness-core"))

from harness import cli, plan as plan_mod  # noqa: E402
from harness.state import CheckpointStore  # noqa: E402


# ---- classification -----------------------------------------------------------

@pytest.mark.parametrize("task,expected", [
    ("fix crash when saving an empty form", "bugfix"),
    ("修复登录页面的崩溃问题", "bugfix"),
    ("refactor the billing module into smaller units", "refactor"),
    ("重构配置加载逻辑", "refactor"),
    ("migrate to the v2 API", "migration"),
    ("升级到 Python 3.12", "migration"),
    ("optimize the report query, it is too slow", "performance"),
    ("性能优化: 加速首页加载", "performance"),
    ("review the auth module for security holes", "review"),
    ("审计支付模块", "review"),
    ("write test coverage for the parser", "testing"),
    ("为核心模块加测试提高覆盖率", "testing"),
    ("design the plugin architecture", "design"),
    ("设计新的消息队列架构", "design"),
    ("add a settings page with a dark mode toggle", "feature-ui"),
    ("新增一个仪表盘页面", "feature-ui"),
    ("create a REST endpoint for orders", "feature-api"),
    ("新增用户查询接口", "feature-api"),
    ("integrate the payment webhook with our billing sync", "feature-integration"),
    ("对接第三方支付网关", "feature-integration"),
    ("add a config flag for retry count", "feature-config"),
    ("新增环境变量配置开关", "feature-config"),
    ("add a database table for sessions", "feature-data"),
    ("新增数据表存储会话", "feature-data"),
    ("build a small helper for text cleanup", "feature-generic"),
])
def test_archetype_classification(task, expected):
    assert plan_mod.detect_task_type(task) == expected


def test_classification_traps():
    # documented trap: "添加迁移" is adding a migration FILE, not a migration task
    assert plan_mod.detect_task_type("添加迁移脚本和数据表") == "feature-data"
    # integration must beat API even when api-ish words are present
    assert plan_mod.detect_task_type("对接第三方支付服务的接口") == "feature-integration"


def test_classifier_precedence_is_verbatim_semantics():
    """Signal ORDER is part of the contract (copied verbatim from CodeLike).
    These pin real precedence outcomes so a future 'cleanup' cannot silently
    change classification behaviour:
      - bugfix signals (incl. "issue") fire before review/design
      - performance signals (incl. "缓存"/"cache") fire before design
      - integration signals (incl. "export") fire before api subtype
    """
    assert plan_mod.detect_task_type("review the auth module for security issues") == "bugfix"
    assert plan_mod.detect_task_type("设计新的缓存架构") == "performance"
    assert plan_mod.detect_task_type("create a REST endpoint for order export") == "feature-integration"


# ---- plan structure -------------------------------------------------------------

def test_plan_bugfix_structure():
    p = plan_mod.plan("fix the crash on empty save")
    assert p["schema"] == 1
    assert p["archetype"] == "bugfix"
    assert [ph["name"] for ph in p["phases"]] == ["Reproduce & Locate", "Fix", "Verify"]
    assert [ph["num"] for ph in p["phases"]] == [1, 2, 3]
    assert all(ph["risk"] in {"LOW", "MEDIUM", "HIGH"} for ph in p["phases"])
    assert len(p["acceptance_criteria"]) >= 3
    assert p["checkpoint_hint"]["stages"] == [ph["name"] for ph in p["phases"]]


def test_first_phase_always_low_risk():
    for archetype in plan_mod.ARCHETYPES:
        p = plan_mod.plan("some task", archetype=archetype)
        assert p["phases"][0]["risk"] == "LOW", archetype


def test_archetype_override_and_validation():
    p = plan_mod.plan("do something vague", archetype="migration")
    assert p["archetype"] == "migration"
    assert p["phases"][1]["risk"] == "HIGH"  # Migrate phase
    with pytest.raises(ValueError):
        plan_mod.plan("x", archetype="not-a-type")
    with pytest.raises(ValueError):
        plan_mod.plan("   ")


def test_generic_fallback_four_phases():
    p = plan_mod.plan("build a small helper for text cleanup")
    assert p["archetype"] == "feature-generic"
    assert [ph["name"] for ph in p["phases"]] == ["Understand", "Design", "Implement", "Verify"]


def test_ac_matches_archetype():
    p = plan_mod.plan("add a database table for sessions")
    assert p["archetype"] == "feature-data"
    assert any("CRUD" in ac for ac in p["acceptance_criteria"])


# ---- determinism & encoding ------------------------------------------------------

def test_deterministic_and_ascii_serializable():
    a = plan_mod.plan("新增用户查询接口, 支持分页")
    b = plan_mod.plan("新增用户查询接口, 支持分页")
    assert a == b
    blob = json.dumps(a, ensure_ascii=True)
    assert blob.isascii()
    assert json.loads(blob) == a  # lossless through ASCII escaping


# ---- checkpoint wiring -------------------------------------------------------------

def test_cli_plan_prints_json(tmp_path, capsys):
    rc = cli.main(["--data-dir", str(tmp_path), "plan", "fix the crash on empty save"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["archetype"] == "bugfix"
    assert "saved_checkpoint" not in out


def test_cli_plan_save_persists_stage0_checkpoint(tmp_path, capsys):
    dd = str(tmp_path)
    rc = cli.main(["--data-dir", dd, "plan", "migrate to the v2 API", "--save"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    exec_id = out["saved_checkpoint"]["execution_id"]
    store = CheckpointStore(tmp_path)
    rec, health = store.load_latest(exec_id)
    assert health["ok"] is True
    assert rec["stage"] == "Plan" and rec["stage_index"] == 0
    assert rec["payload"]["archetype"] == "migration"
    # the saved plan's phases are then usable as checkpoint stages
    store.save(exec_id, rec["payload"]["phases"][0]["name"], {"notes": "impact assessed"},
               stage_index=1)
    assert store.verify(exec_id)["ok"] is True


def test_cli_plan_bad_archetype_exit_2(tmp_path, capsys):
    assert cli.main(["--data-dir", str(tmp_path), "plan", "t",
                     "--archetype", "nope"]) == 2
    assert "unknown archetype" in capsys.readouterr().err


# ---- standalone ---------------------------------------------------------------------

def test_module_has_no_legacy_dependency():
    src = Path(plan_mod.__file__).read_text(encoding="utf-8")
    assert "F:\\Claude" not in src
    assert "brain." not in src and "import brain" not in src
