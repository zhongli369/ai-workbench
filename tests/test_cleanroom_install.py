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

# Vars a brand-new machine would carry; everything else is developer-private
# and must not reach the subprocess under test.
_FRESH_ALLOW = {"PATH", "SystemRoot", "SystemDrive", "SYSTEMDRIVE", "ComSpec",
                "ProgramFiles", "ProgramFiles(x86)", "PROCESSOR_ARCHITECTURE",
                "NUMBER_OF_PROCESSORS", "OS", "windir", "PATHEXT", "USERPROFILE",
                "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TMPDIR",
                "TZ", "LANG", "LC_ALL", "HOMEDRIVE", "HOMEPATH"}


def _fresh_env(base: Path) -> dict:
    """A scrubbed, fresh-user-like env pointing HOME/APPDATA into `base`."""
    env = {k: v for k, v in os.environ.items() if k in _FRESH_ALLOW}
    for d in ("home", "localappdata", "appdata", "tmp"):
        (base / d).mkdir(parents=True, exist_ok=True)
    env["USERPROFILE"] = str(base / "home")
    env["HOME"] = str(base / "home")
    env["LOCALAPPDATA"] = str(base / "localappdata")
    env["APPDATA"] = str(base / "appdata")
    env["TEMP"] = str(base / "tmp")
    env["TMP"] = str(base / "tmp")
    return env


def run_wb(*args, cwd=None, env=None):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          cwd=cwd or RC, env=env, timeout=120)


def install(target, *extra):
    return run_wb("--target", str(target), "install", "--yes", *extra)


# ---------------- install ----------------

def test_install_renders_all_paths_and_never_leaks_personal_paths(tmp_path):
    target = tmp_path / "wb"
    r = install(target)
    assert r.returncode == 0, r.stdout + r.stderr
    # The install completion hint must print a VALID CLI order: --target is
    # a GLOBAL option, so it must precede the `launch` subcommand. Regression:
    # v0.1.0-preview.3 printed `launch --target X`, which argparse rejects as
    # "unrecognized arguments: --target X".
    hints = [ln.strip() for ln in r.stdout.splitlines() if "启动: python " in ln]
    assert len(hints) == 1 and "launch --target" not in hints[0]
    toks = hints[0].replace('"', "").split()
    assert "--target" in toks and toks.index("--target") < toks.index("launch")
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
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
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
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
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
    # PROJECTS.md quick-reference template is authored at first install...
    projects = target / "PROJECTS.md"
    assert projects.is_file()
    assert "项目登记表" in projects.read_text(encoding="utf-8")
    # ...and the user's own edits survive a reinstall (it is user data,
    # never clobbered by the stock template).
    projects.write_text("# my own projects\n", encoding="utf-8")
    gate = target / "harness-data" / "gate.json"
    cfg = json.loads(gate.read_text(encoding="utf-8"))
    cfg["mode"] = "enforce"
    gate.write_text(json.dumps(cfg), encoding="utf-8")
    r = install(target)  # reinstall
    assert r.returncode == 0 and "幂等" in r.stdout
    assert json.loads(gate.read_text(encoding="utf-8"))["mode"] == "enforce"
    assert projects.read_text(encoding="utf-8") == "# my own projects\n"


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


def test_launch_passthrough_extra_args(tmp_path):
    """Regression (FINAL SEAL Agent A-D1): docs/multi-project.md told users to
    pass --add-dir through launch, but argparse rejected it (exit 2). Extra
    args after `--` must reach the printed launcher command unchanged."""
    target = tmp_path / "wb"
    assert install(target).returncode == 0
    bare = run_wb("--target", str(target), "launch")
    assert bare.returncode == 0
    assert "--add-dir" not in bare.stdout
    r = run_wb("--target", str(target), "launch", "--", "--add-dir", str(tmp_path / "proj"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "--add-dir" in r.stdout and str(tmp_path / "proj") in r.stdout
    # REMAINDER also tolerates the explicit separator being absent when the
    # first extra token does not look like an option
    r2 = run_wb("--target", str(target), "launch", "plain-arg")
    assert r2.returncode == 0 and "plain-arg" in r2.stdout


def test_doctor_never_mutates_and_exits_clean(tmp_path):
    before = set(tmp_path.iterdir())
    r = run_wb("--target", str(tmp_path / "wb"), "doctor")
    assert r.returncode in (0, 1)
    assert set(tmp_path.iterdir()) == before  # nothing written


# ---------------- uninstall ----------------

def test_reinstall_preserves_manifest_ownership(tmp_path):
    """Regression (FINAL SEAL Agent C-D1): an idempotent reinstall skipped
    re-writing existing user files (PROJECTS.md) and rebuilt the manifest
    from scratch — silently dropping their ownership, so a later uninstall
    left them behind (violating the owns-only sweep contract). The reinstall
    must MERGE the previous manifest's file list."""
    target = tmp_path / "wb"
    assert install(target).returncode == 0
    projects = target / "PROJECTS.md"
    assert projects.is_file()
    before = json.loads((target / "install-manifest.json").read_text(encoding="utf-8"))["files"]
    assert str(projects) in before
    # simulate the user having edited PROJECTS.md (content must survive)
    projects.write_text("# my projects\nAIMC -> F:/x\n", encoding="utf-8")
    assert install(target).returncode == 0  # idempotent reinstall
    after = json.loads((target / "install-manifest.json").read_text(encoding="utf-8"))["files"]
    assert str(projects) in after, "reinstall lost PROJECTS.md ownership"
    assert set(before) <= set(after), "reinstall truncated the manifest"
    assert "AIMC" in projects.read_text(encoding="utf-8")  # user content intact
    r = run_wb("--target", str(target), "uninstall", "--yes", "--purge-data")
    assert r.returncode == 0
    assert not projects.exists(), "owned PROJECTS.md survived uninstall"
    assert not target.exists()


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
    assert not (target / "PROJECTS.md").exists()  # owned file removed too
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


def test_launcher_scripts_quote_paths_with_spaces(tmp_path):
    """Regressions: a target like '...\\My Projects\\wb' must produce launch
    scripts that quote the path. Unquoted, Set-Location and the --settings arg
    both break on spaces (POSIX template already quoted; PS1 did not)."""
    target = tmp_path / "My Projects" / "wb"
    r = install(target)
    assert r.returncode == 0, r.stdout + r.stderr
    ps1 = (target / "launch" / "workbench.ps1").read_text(encoding="utf-8")
    sh = (target / "launch" / "workbench.sh").read_text(encoding="utf-8")
    rp = str(target.resolve())
    rpx = rp.replace("\\", "/")
    assert f'Set-Location "{rp}"' in ps1
    assert "--settings" in ps1
    assert f'"{rp}\\launch\\vnext.settings.json"' in ps1
    assert f'cd "{rpx}"' in sh
    assert f'--settings "{rpx}/launch/vnext.settings.json"' in sh
    # still nothing leaks the builder machine (rendered files may legitimately
    # contain this machine's TARGET path — hence the tmp_path lives under the
    # user dir; only the builder's own F:\\Claude must never appear)
    assert "F:\\Claude" not in ps1 and "F:\\Claude" not in sh


def test_launcher_defaults_to_zero_mcp_and_optin_project_config(tmp_path):
    """Default MCP = 0 is enforced, not merely documented.

    --strict-mcp-config ignores every global/user MCP registration.  The
    project's .mcp.json is loaded only when it exists (Playwright capability
    writes it on demand), so on-demand wiring still works without re-opening
    the global 200+-tool servers.
    """
    target = tmp_path / "wb"
    r = install(target)
    assert r.returncode == 0, r.stdout + r.stderr
    ps1 = (target / "launch" / "workbench.ps1").read_text(encoding="utf-8")
    sh = (target / "launch" / "workbench.sh").read_text(encoding="utf-8")
    for script in (ps1, sh):
        assert "--strict-mcp-config" in script
        assert ".mcp.json" in script
    assert "Test-Path -LiteralPath" in ps1
    assert '[ -f "' in sh
    launch_settings = json.loads(
        (target / "launch" / "vnext.settings.json").read_text(encoding="utf-8"))
    assert "**/.claude/rules/ecc/**" in launch_settings["claudeMdExcludes"]
    assert not (target / ".mcp.json").exists(), "default install adds zero MCP"


# ---------------- RC hygiene ----------------

def test_rc_tree_has_no_personal_paths_or_secrets():
    """The RC itself must be publishable: no builder paths, no home dir refs.

    Scans the publishable set (git-tracked files) — gitignored local evidence
    like tools/bench/results/ never ships and is not the release boundary.
    """
    import re
    import subprocess
    r = subprocess.run(["git", "ls-files"], capture_output=True, text=True, encoding="utf-8",
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


# ---------------- clean-room error quality (regressions) ----------------

def test_install_into_existing_file_target_is_clean_failure(tmp_path):
    """--target pointing at a FILE must be a one-line FAIL, never a
    NotADirectoryError traceback, and must leave the file untouched."""
    f = tmp_path / "wb"
    f.write_text("not a dir", encoding="utf-8")
    r = run_wb("--target", str(f), "install", "--yes")
    assert r.returncode == 1
    assert "不是目录" in r.stdout
    assert "Traceback" not in r.stdout and "Traceback" not in r.stderr
    assert f.read_text(encoding="utf-8") == "not a dir"


def test_doctor_into_existing_file_target_is_clean_failure(tmp_path):
    """doctor is read-only but must still diagnose a file-as-target cleanly."""
    f = tmp_path / "wb"
    f.write_text("not a dir", encoding="utf-8")
    r = run_wb("--target", str(f), "doctor")
    assert r.returncode == 1
    assert "不是目录" in r.stdout
    assert "Traceback" not in r.stdout + r.stderr


def test_install_into_uncreatable_ancestor_is_clean_failure(tmp_path):
    """A file node in the target path (so no dir can ever be created there)
    is a one-line FAIL, not a FileNotFoundError mkdir cascade."""
    f = tmp_path / "blocker"
    f.write_text("i am a file", encoding="utf-8")
    target = f / "sub" / "wb"
    r = run_wb("--target", str(target), "install", "--yes")
    assert r.returncode == 1
    assert "文件节点" in r.stdout
    assert "Traceback" not in r.stdout + r.stderr


def test_doctor_never_prints_traceback_under_scrubbed_env(tmp_path):
    """A fresh-user env with an unusable console must not leak a
    UnicodeDecodeError (external captures are byte + errors='replace')."""
    env = _fresh_env(tmp_path)
    r = run_wb("--target", str(tmp_path / "wb"), "doctor", env=env)
    assert r.returncode in (0, 1)
    assert "Traceback" not in r.stdout + r.stderr
    assert "UnicodeDecodeError" not in r.stdout + r.stderr


def test_external_capture_is_decode_safe(monkeypatch):
    """_claude_version() and the PowerShell policy probe decode bytes with
    errors='replace'; non-locale output can never raise in a capture thread."""
    import argparse
    import importlib.util
    spec = importlib.util.spec_from_file_location("wbmod", str(CLI))
    wb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wb)

    class FakeProc:
        def __init__(self, out):
            self.stdout = out
            self.stderr = b""

    import subprocess as real_sp

    def fake_run(argv, capture_output=True, timeout=15):
        # simulate a succeed-but-binary console (UTF-16LE garbage + newline)
        if "powershell" in argv[0].lower():
            return FakeProc(b"RemoteSigned\r\n\x85\x02")
        return FakeProc(b"\xff\xfe\x81\x01 ok\r\n")

    class FakeSubprocess:
        """Stand-in for the workbench module's own `subprocess` reference.

        Patching wb.subprocess.run directly would replace the PROCESS-GLOBAL
        subprocess.run (wb.subprocess IS the global module object), breaking
        unrelated stdlib callers — e.g. platform.release() on Windows <
        3.12 shells out via check_output, which calls run(stdout=PIPE) and
        dies on fake_run's strict signature. Scope the patch to the wb
        module attribute instead; everything else delegates to the real
        module.
        """
        run = staticmethod(fake_run)
        TimeoutExpired = real_sp.TimeoutExpired

        def __getattr__(self, name):  # delegate everything else
            return getattr(real_sp, name)

    monkeypatch.setattr(wb, "subprocess", FakeSubprocess())
    v = wb._claude_version()
    assert isinstance(v, str)  # replacement-decoded, never raised
    # Powershell probe path: cmd_doctor must complete without exception.
    rc = wb.cmd_doctor(argparse.Namespace(target=None))
    assert rc in (0, 1)
