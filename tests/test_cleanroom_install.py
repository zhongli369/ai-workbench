"""Clean-room install/uninstall tests. No Claude Code, no network, no F:\\Claude.

Simulates a stranger's machine: install into a fresh tmp dir, exercise the
installed artifacts, then uninstall and verify nothing leaks outside target.
Run: python -m pytest tests/ -q   (from RC root)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RC = Path(__file__).resolve().parent.parent
CLI = RC / "tools" / "workbench.py"


def run_wb(*args, cwd=None):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, cwd=cwd or RC, timeout=120)


def install(target, *extra):
    return run_wb("--target", str(target), "install", "--yes", *extra)


# ---------------- install ----------------

def test_install_renders_all_paths_and_never_leaks_personal_paths(tmp_path):
    target = tmp_path / "wb"
    r = install(target)
    assert r.returncode == 0, r.stdout + r.stderr
    # rendered configs exist and contain the target path, not template holes
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert str(target.resolve()).replace("\\", "/") in settings["env"]["HARNESS_DATA_DIR"]
    # no template holes or BUILDER-machine paths anywhere in the installed tree.
    # rendered files (settings/launch/manifest) legitimately contain the target
    # path of THIS machine; copied payload files must contain no machine paths.
    rendered = {"install-manifest.json", "settings.json", "vnext.settings.json",
                "workbench.ps1", "workbench.sh"}
    for p in target.rglob("*"):
        if p.is_file() and p.suffix in {".json", ".ps1", ".sh", ".md", ".py"}:
            t = p.read_text(encoding="utf-8", errors="replace")
            assert "{{ROOT}}" not in t, p
            assert "F:\\Claude" not in t and "F:/Claude" not in t, p  # builder path, never ok
            if p.name in rendered or "harness-data" in p.parts:
                continue
            assert "14679" not in t, p  # copied payload must be machine-neutral
    # components present
    assert len(list((target / ".claude" / "agents").glob("*.md"))) == 16
    assert len(list((target / ".claude" / "skills").iterdir())) >= 29
    assert (target / "vendor" / "ecc" / "LICENSE").is_file()
    assert (target / "harness-core" / "harness" / "cli.py").is_file()
    assert json.loads((target / "harness-data" / "gate.json").read_text())["mode"] == "audit"


def test_installed_harness_cli_roundtrip_and_gate_enforce(tmp_path):
    target = tmp_path / "wb"
    assert install(target).returncode == 0
    cli = target / "harness-core" / "harness" / "cli.py"
    env = {**os.environ, "HARNESS_DATA_DIR": str(target / "harness-data")}
    def h(*args):
        return subprocess.run([sys.executable, str(cli), *args],
                              capture_output=True, text=True, env=env, timeout=60)
    # feedback roundtrip
    rec = json.loads(h("feedback", "record", "--project-id", "demo",
                       "--cause", "c", "--summary", "s").stdout)
    rows = json.loads(h("feedback", "query", "--project-id", "demo", "--json").stdout)
    assert rows[0]["record_id"] == rec["record_id"]
    # gate: audit default -> check reports audit; enforce -> block
    assert h("gate", "mode", "--set", "enforce").returncode == 0
    out = json.loads(h("gate", "check", "git push origin main").stdout)
    assert out["decision"] == "block"
    # hook subprocess e2e on the INSTALLED copy
    hook = target / "hooks" / "harness_gate.py"
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
    r = subprocess.run([sys.executable, str(hook)], input=payload,
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2 and "ENFORCE" in r.stderr


def test_dry_run_writes_nothing(tmp_path):
    target = tmp_path / "wb"
    r = install(target, "--dry-run")
    assert r.returncode == 0
    assert not target.exists() or not any(target.iterdir())


def test_install_refuses_foreign_dir_then_force_backs_up(tmp_path):
    target = tmp_path / "wb"
    target.mkdir()
    (target / "strangers-file.txt").write_text("do not touch", encoding="utf-8")
    r1 = install(target)
    assert r1.returncode == 1 and "FAIL" in r1.stdout
    assert (target / "strangers-file.txt").is_file()  # untouched
    r2 = install(target, "--force")
    assert r2.returncode == 0
    baks = list(tmp_path.glob("wb.bak-*"))
    assert len(baks) == 1 and (baks[0] / "strangers-file.txt").is_file()


def test_reinstall_is_idempotent_and_preserves_user_gate_config(tmp_path):
    target = tmp_path / "wb"
    assert install(target).returncode == 0
    gate = target / "harness-data" / "gate.json"
    cfg = json.loads(gate.read_text(encoding="utf-8"))
    cfg["mode"] = "enforce"
    gate.write_text(json.dumps(cfg), encoding="utf-8")
    r = install(target)  # reinstall
    assert r.returncode == 0 and "幂等" in r.stdout
    assert json.loads(gate.read_text(encoding="utf-8"))["mode"] == "enforce"


# ---------------- status / launch / benchmark ----------------

def test_status_launch_benchmark(tmp_path):
    target = tmp_path / "wb"
    assert run_wb("--target", str(target), "status").returncode == 1  # not installed
    assert install(target).returncode == 0
    s = run_wb("--target", str(target), "status")
    assert s.returncode == 0 and json.loads(s.stdout)["version"]
    l = run_wb("--target", str(target), "launch")
    assert l.returncode == 0 and ("workbench.ps1" in l.stdout or "workbench.sh" in l.stdout)
    b = run_wb("--target", str(target), "benchmark")
    assert b.returncode == 0 and "L0" in b.stdout


def test_doctor_never_mutates_and_exits_clean(tmp_path):
    before = set(tmp_path.iterdir())
    r = run_wb("--target", str(tmp_path / "wb"), "doctor")
    assert r.returncode in (0, 1)
    assert set(tmp_path.iterdir()) == before  # nothing written


# ---------------- uninstall ----------------

def test_uninstall_removes_only_owned_files_and_preserves_data(tmp_path):
    target = tmp_path / "wb"
    assert install(target).returncode == 0
    # user data created after install
    data_file = target / "harness-data" / "feedback.jsonl"
    data_file.write_text('{"ts":"x","project_id":"demo","failure_cause":"c","task_summary":"s"}\n',
                         encoding="utf-8")
    stranger = target / "user-added-note.md"
    stranger.write_text("user's own file", encoding="utf-8")
    # without --yes: nothing happens
    assert run_wb("--target", str(target), "uninstall").returncode == 0
    assert (target / "CLAUDE.md").is_file()
    # with --yes: owned files gone, data + foreign file preserved
    r = run_wb("--target", str(target), "uninstall", "--yes")
    assert r.returncode == 0
    assert not (target / "CLAUDE.md").exists()
    assert not (target / "harness-core").exists()
    assert data_file.is_file() and stranger.is_file()
    # purge removes everything
    r2 = run_wb("--target", str(target), "uninstall", "--yes", "--purge-data")
    assert r2.returncode == 0
    assert not target.exists()


def test_uninstall_refuses_without_manifest(tmp_path):
    target = tmp_path / "wb"
    target.mkdir()
    (target / "precious.txt").write_text("x", encoding="utf-8")
    r = run_wb("--target", str(target), "uninstall", "--yes")
    assert r.returncode == 1
    assert (target / "precious.txt").is_file()


def test_project_scope_installs_into_cwd(tmp_path):
    proj = tmp_path / "my-project"
    proj.mkdir()
    r = run_wb("install", "--scope", "project", "--yes", cwd=proj)
    assert r.returncode == 0
    assert (proj / ".ai-workbench" / "install-manifest.json").is_file()


def test_install_target_with_spaces_and_non_ascii(tmp_path):
    """Paths like 'C:\\Users\\张三\\My Projects\\wb' must round-trip."""
    target = tmp_path / "my projects 工作 台" / "wb"
    r = install(target)
    assert r.returncode == 0, r.stdout + r.stderr
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert str(target.resolve()).replace("\\", "/") in settings["env"]["HARNESS_DATA_DIR"]
    s = run_wb("--target", str(target), "status")
    assert s.returncode == 0 and json.loads(s.stdout)["installed"]
    u = run_wb("--target", str(target), "uninstall", "--yes", "--purge-data")
    assert u.returncode == 0 and not target.exists()


# ---------------- RC hygiene ----------------

def test_rc_tree_has_no_personal_paths_or_secrets():
    """The RC itself must be publishable: no builder paths, no home dir refs.

    Scans the publishable set (git-tracked files) — gitignored local evidence
    like tools/bench/results/ never ships and is not the release boundary.
    """
    import re
    import subprocess
    r = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                       timeout=60, cwd=RC)
    assert r.returncode == 0, "hygiene contract requires a git checkout"
    bad = []
    for rel in r.stdout.splitlines():
        p = RC / rel
        if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts:
            continue
        if p.suffix not in {".py", ".md", ".json", ".ps1", ".sh", ".yml", ".txt"}:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        # this very test file mentions the patterns; skip tests dir
        if "tests" in p.relative_to(RC).parts:
            continue
        for pat in (r"F:[\\/]Claude", r"14679",
                    r"[A-Za-z]:[\\/]Users[\\/](?=[A-Za-z0-9_.-]*[A-Za-z0-9])[A-Za-z0-9_.-]+[\\/]",
                    r"sk-[A-Za-z0-9]{10,}", r"ghp_[A-Za-z0-9]{10,}"):
            if re.search(pat, t):
                bad.append((str(p.relative_to(RC)), pat))
    assert bad == [], f"personal paths/secrets in RC: {bad}"


def test_hygiene_gate_catches_user_profile_paths_but_not_placeholders():
    """check_hygiene.PATTERNS must catch real user-profile paths (the M5
    results/ blind spot) while tolerating doc placeholders like C:\\Users\\...\\"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_hygiene", RC / "tools" / "check_hygiene.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import re
    pats = [re.compile(p) for p, _ in mod.PATTERNS]
    hits = lambda s: any(p.search(s) for p in pats)
    assert hits(r"workspace = C:\Users\someone\AppData\Local\Temp\bench_t1\ws")
    assert hits("C:/Users/another.user/project")
    assert not hits(r"# is passed as e.g. C:\Users\...\project.")
    assert not hits(r"extract to <your-user-dir>")
