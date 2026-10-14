"""Frozen public surface verifier (P1.2, adapted from SystemKernel's
stability_freeze mechanism — reimplemented lightweight, ~1/10 the code).

Freezes the PUBLIC promises external users may depend on:
  1. CLI surface of tools/workbench.py and harness-core/harness/cli.py
     (commands / flags / positionals / choices — extracted via stdlib AST,
     never executed; counts are always computed, never hand-written)
  2. harness JSONL data-format schemas, captured BEHAVIORALLY: the real
     writers run in a temp data dir and the emitted record shapes are the
     contract (fields + python types)
  3. installer settings template (top-level keys, env keys, hook matchers)

Superset rule: additive change is FREE (new command/flag/field/choice =
"additive", exit 0). Removal, retype, or shrinking a choices list is
BREAKING (exit 1). Intentional upgrades go through
  --accept-new --bump major|minor --rationale "..."
which regenerates docs/surface.json and appends a dated history entry —
the frozen file is the audit trail. Internal refactors that keep the
surface are invisible to this gate by design.

Run:  python tools/check_public_surface.py [--json]
      python tools/check_public_surface.py --accept-new --bump minor --rationale "..."
"""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "harness-core"))

from cli_surface import extract_cli_surface  # noqa: E402

SURFACE_PATH = REPO / "docs" / "surface.json"


# ---------------------------------------------------------------- current surface

def _shapes_from_records(records: list[dict]) -> dict:
    """{field: typename} union across records; conflicts -> 'mixed'."""
    shape: dict[str, str] = {}
    for rec in records:
        for k, v in rec.items():
            t = type(v).__name__
            shape[k] = shape.get(k, t) if shape.get(k, t) == t else "mixed"
    return dict(sorted(shape.items()))


def _behavioral_schemas(tmp: Path) -> dict:
    """Run the real writers in a temp data dir; the emitted JSONL shapes are
    the data-format contract. Fields a default write emits are REQUIRED —
    a future version may add fields but never drop/retype these."""
    from harness import feedback, gate, telemetry

    d = tmp / "data"
    feedback.record(d, project_id="surface-probe", cause="probe",
                    summary="surface probe", phases=["p1"])
    gate.write_config(d, mode="audit")
    # NB: the approval pattern must NOT match the token-probe command below,
    # or the multi-use approval short-circuits and the token is never consumed
    gate.approve(d, pattern=r"npm publish.*", ttl=60, note="probe")
    gate.log_decision(d, mode="audit", decision="audit", command="probe cmd",
                      matched=r"npm publish.*", token_hash="0" * 64)
    g = gate.approve_once(d, action="git push origin probe", note="probe")
    gate.write_config(d, mode="enforce")
    gate.evaluate(d, "git push origin probe", token=g["token"])
    telemetry.log(d, cmd="surface.probe", project_id="surface-probe", argv=["probe"])

    def lines(name):
        p = d / name
        if not p.is_file():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

    grants = [e for e in lines("gate-tokens.jsonl") if e.get("type") == "grant"]
    consumes = [e for e in lines("gate-tokens.jsonl") if e.get("type") == "consume"]
    schemas = {
        "feedback.jsonl:record": _shapes_from_records(lines("feedback.jsonl")),
        "gate-approvals.jsonl:approval": _shapes_from_records(lines("gate-approvals.jsonl")),
        "gate-audit.jsonl:decision": _shapes_from_records(lines("gate-audit.jsonl")),
        "gate-tokens.jsonl:grant": _shapes_from_records(grants),
        "gate-tokens.jsonl:consume": _shapes_from_records(consumes),
        "telemetry.jsonl:entry": _shapes_from_records(lines("telemetry.jsonl")),
        "gate.json:config": _shapes_from_records(
            [json.loads((d / "gate.json").read_text(encoding="utf-8"))]),
    }
    missing = [k for k, v in schemas.items() if not v]
    if missing:
        raise RuntimeError(f"behavioral probe produced no records for: {missing}")
    return schemas


def _settings_surface() -> dict:
    import workbench  # tools/ on sys.path
    tmpl = workbench.SETTINGS_TMPL
    matchers = sorted({h.get("matcher", "") for h in tmpl.get("hooks", {}).get("PreToolUse", [])})
    return {"top_level_keys": sorted(tmpl.keys()),
            "env_keys": sorted(tmpl.get("env", {}).keys()),
            "pre_tool_use_matchers": matchers}


def current_surface(scripts_root: Path | None = None) -> dict:
    root = Path(scripts_root) if scripts_root else REPO
    with tempfile.TemporaryDirectory() as td:
        schemas = _behavioral_schemas(Path(td))
    return {
        "cli": {
            "workbench.py": extract_cli_surface(root / "tools" / "workbench.py"),
            "harness/cli.py": extract_cli_surface(root / "harness-core" / "harness" / "cli.py"),
        },
        "jsonl_schemas": schemas,
        "settings_template": _settings_surface(),
    }


# ---------------------------------------------------------------- comparison

def _cmp_entries(frozen: dict, current: dict, breaking: list, additive: list,
                 path: str, noun: str):
    """Compare {name: {"choices": ...}} entry maps under the superset rule."""
    for name, f_ent in frozen.items():
        c_ent = current.get(name)
        if c_ent is None:
            breaking.append(f"{path}: {noun} removed: {name}")
            continue
        f_ch, c_ch = f_ent.get("choices"), c_ent.get("choices")
        if (f_ch is None) != (c_ch is None):
            breaking.append(f"{path}: {name} choices retyped")
        elif f_ch and c_ch:
            for v in f_ch:
                if v not in c_ch:
                    breaking.append(f"{path}: {name} choice removed: {v}")
            for v in c_ch:
                if v not in f_ch:
                    additive.append(f"{path}: {name} choice added: {v}")
    for name in current:
        if name not in frozen:
            additive.append(f"{path}: {noun} added: {name}")


def _cmp_cli(frozen: dict, current: dict, breaking: list, additive: list, path: str):
    _cmp_entries(frozen.get("global_flags", {}), current.get("global_flags", {}),
                 breaking, additive, path, "global flag")
    f_cmds, c_cmds = frozen.get("commands", {}), current.get("commands", {})
    for name in f_cmds:
        if name not in c_cmds:
            breaking.append(f"{path}: command removed: {name}")
    for name in c_cmds:
        if name not in f_cmds:
            additive.append(f"{path}: command added: {name}")
    for cmd, f_spec in f_cmds.items():
        c_spec = c_cmds.get(cmd)
        if c_spec is None:
            continue  # already reported
        _cmp_entries(f_spec.get("flags", {}), c_spec.get("flags", {}),
                     breaking, additive, f"{path}: {cmd}", "flag")
        _cmp_entries(f_spec.get("positionals", {}), c_spec.get("positionals", {}),
                     breaking, additive, f"{path}: {cmd}", "positional")


def _cmp_schemas(frozen: dict, current: dict, breaking: list, additive: list):
    for name, f_fields in frozen.items():
        c_fields = current.get(name)
        if c_fields is None:
            breaking.append(f"schema removed: {name}")
            continue
        for field, f_type in f_fields.items():
            if field not in c_fields:
                breaking.append(f"{name}: field removed: {field}")
            elif c_fields[field] != f_type:
                breaking.append(f"{name}: field retyped: {field} "
                                f"{f_type} -> {c_fields[field]}")
        for field in c_fields:
            if field not in f_fields:
                additive.append(f"{name}: field added: {field}")
    for name in current:
        if name not in frozen:
            additive.append(f"schema added: {name}")


def _cmp_settings(frozen: dict, current: dict, breaking: list, additive: list):
    for key in ("top_level_keys", "env_keys", "pre_tool_use_matchers"):
        for v in frozen.get(key, []):
            if v not in current.get(key, []):
                breaking.append(f"settings_template.{key} removed: {v}")
        for v in current.get(key, []):
            if v not in frozen.get(key, []):
                additive.append(f"settings_template.{key} added: {v}")


def compare(frozen: dict, current: dict) -> dict:
    breaking: list[str] = []
    additive: list[str] = []
    for cli_name, f_surf in frozen.get("cli", {}).items():
        c_surf = current.get("cli", {}).get(cli_name)
        if c_surf is None:
            breaking.append(f"cli removed: {cli_name}")
            continue
        _cmp_cli(f_surf, c_surf, breaking, additive, f"cli:{cli_name}")
    _cmp_schemas(frozen.get("jsonl_schemas", {}),
                 current.get("jsonl_schemas", {}), breaking, additive)
    _cmp_settings(frozen.get("settings_template", {}),
                  current.get("settings_template", {}), breaking, additive)
    return {"breaking": breaking, "additive": additive,
            "ok": not breaking}


# ---------------------------------------------------------------- emit / accept

def emit(surface: dict, history: list | None = None) -> dict:
    """Deterministic baseline document (no timestamps outside history)."""
    return {"surface_version": 1,
            "generator": "tools/check_public_surface.py --accept-new",
            "cli": surface["cli"],
            "jsonl_schemas": surface["jsonl_schemas"],
            "settings_template": surface["settings_template"],
            "history": history or []}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="frozen public surface verifier")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--surface", default=None, help="frozen surface.json path")
    ap.add_argument("--accept-new", action="store_true",
                    help="regenerate the frozen surface from the current tree")
    ap.add_argument("--bump", choices=["major", "minor"], default=None,
                    help="required with --accept-new: major if breaking, minor if additive-only")
    ap.add_argument("--rationale", default=None, help="required with --accept-new")
    args = ap.parse_args(argv)

    root = Path(args.root)
    surface_path = Path(args.surface) if args.surface else root / "docs" / "surface.json"
    current = current_surface(root)

    if args.accept_new:
        if not args.bump or not args.rationale:
            print("--accept-new requires --bump major|minor and --rationale", file=sys.stderr)
            return 2
        old_history = []
        if surface_path.is_file():
            old = json.loads(surface_path.read_text(encoding="utf-8"))
            old_history = old.get("history", [])
            diff = compare(old, current)
            if diff["breaking"] and args.bump != "major":
                for b in diff["breaking"]:
                    print(f"BREAKING: {b}", file=sys.stderr)
                print("breaking changes require --bump major", file=sys.stderr)
                return 2
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "bump": args.bump, "rationale": args.rationale[:300]}
        doc = emit(current, old_history + [entry])
        surface_path.parent.mkdir(parents=True, exist_ok=True)
        surface_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        print(f"surface frozen -> {surface_path} ({args.bump}: {args.rationale})")
        return 0

    if not surface_path.is_file():
        print(f"frozen surface missing: {surface_path}\n"
              f"create it with --accept-new --bump minor --rationale \"baseline\"",
              file=sys.stderr)
        return 2
    frozen = json.loads(surface_path.read_text(encoding="utf-8"))
    rep = compare(frozen, current)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for b in rep["breaking"]:
            print(f"BREAKING: {b}")
        for a in rep["additive"]:
            print(f"additive: {a}")
        print(f"public surface: {'PASS' if rep['ok'] else 'FAIL'} "
              f"({len(rep['breaking'])} breaking, {len(rep['additive'])} additive)")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
