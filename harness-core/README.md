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
- **telemetry** — invocation ledger with self-exclusion: reader commands
  (`telemetry`, `feedback stats`, `report`, `gate check`) are never logged,
  every row carries a source label (`cli` / `bench` via `HARNESS_BENCH=1` /
  `synthetic`), and the summary's adoption view counts only real `cli`
  invocations — benchmarks can never masquerade as product usage.
- **checkpoint** — versioned task-state checkpoints (t8-class integrity):
  append-only JSONL, per-record payload sha256, torn-tail detection with
  explicit health (damage is never indistinguishable from absence), BOM/CRLF
  tolerant reads, pure-ASCII writes, crash marker for in-flight stages,
  parent-chain + stage-order verification. Raw evidence is never truncated,
  overwritten, or "repaired" — `verify` reports, the human decides.
- **plan** — deterministic DEEP-mode phase scaffold: bilingual 13-archetype
  classifier → ordered phases with per-phase risk + acceptance criteria.
  On-demand CLI only, never auto-injected; phases double as checkpoint
  stage names for long-horizon work. (Minimal extraction of the retired
  CodeLike planning kernel — zero legacy-repo dependency.)

## Usage

```bash
python harness/cli.py feedback record --cause silent_exit --summary "..." --project-id demo
python harness/cli.py feedback query --project-id demo --keyword cache --json
python harness/cli.py feedback promote --record-id fb-xxx --status verified
python harness/cli.py report --project-id demo
python harness/cli.py gate mode --set enforce
python harness/cli.py gate approve --pattern "git push.*" --ttl 600
python harness/cli.py gate approve --once --action "git push origin main"   # single-use token (awt-...), printed once
python harness/cli.py gate check "git push origin main" --token awt-<token>
python harness/cli.py telemetry
python harness/cli.py plan "migrate to the v2 API" --save     # DEEP scaffold → stage-0 checkpoint
python harness/cli.py checkpoint begin --exec migrate-to-the-v2-api --stage "Assess Impact" --index 1
python harness/cli.py checkpoint save  --exec migrate-to-the-v2-api --stage "Assess Impact" --index 1 --payload '{"done": true}'
python harness/cli.py checkpoint load --exec migrate-to-the-v2-api
python harness/cli.py checkpoint verify --exec migrate-to-the-v2-api   # exit 1 on any damage
python harness/cli.py checkpoint list
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
python -m pytest tests/ -q     # 120 contracts, stdlib + pytest only
```

## Honest limits

- Concurrency: in-process lock + append; multi-process writers not stress-tested.
- No delete/edit of records (append-only by design); status via promotions ledger.
- Verified on Windows; POSIX paths supported, covered by CI.
