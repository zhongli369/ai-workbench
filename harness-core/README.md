# harness-core

Deterministic, stdlib-only failure-memory and gate toolkit for Claude Code (or any agent).
No network, no upload, no machine-specific paths. Data lives in one local directory
(JSONL, append-only).

## Components

- **feedback** — append failure records; query per project; per-cause stats.
  Records carry `source` (user-correction outranks model-inference) and `confidence`.
- **report** — recurring failure causes → human-review promotion proposals.
- **promote** — append-only status machine: candidate → verified → promoted / retired.
  Promotion never auto-modifies any config or rules.
- **gate** — three-tier irreversible-action gate: `disabled` / `audit` (logs only,
  NOT protection) / `enforce` (blocks without approval, fail-closed on config error).
- **telemetry** — invocation ledger; the `telemetry` reader itself is never counted.

## Usage

```bash
python harness/cli.py feedback record --cause silent_exit --summary "..." --project-id demo
python harness/cli.py feedback query --project-id demo --keyword cache --json
python harness/cli.py feedback promote --record-id fb-xxx --status verified
python harness/cli.py report --project-id demo
python harness/cli.py gate mode --set enforce
python harness/cli.py gate approve --pattern "git push.*" --ttl 600
python harness/cli.py gate check "git push origin main"
python harness/cli.py telemetry
```

- Data dir precedence: `--data-dir` > `HARNESS_DATA_DIR` > platform default
  (`%LOCALAPPDATA%\harness` / `$XDG_DATA_HOME/harness` / `~/.local/share/harness`).
- project_id precedence: `--project-id` > `HARNESS_PROJECT_ID` > `.harness-project`
  file at project root > git remote (credentials stripped) > path hash.

## PreToolUse hook (Claude Code)

```json
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "python <abs-path>/hooks/harness_gate.py"}]}]}}
```

Note: `claude --print` (non-interactive) does not execute hooks — gate enforcement
applies to interactive sessions (verified 2026-10, CC 2.1.x).

## Tests

```bash
python -m pytest tests/ -q     # 38 contracts, stdlib + pytest only
```

## Honest limits

- Concurrency: in-process lock + append; multi-process writers not stress-tested.
- No delete/edit of records (append-only by design); status via promotions ledger.
- Verified on Windows; POSIX paths supported, covered by CI.
