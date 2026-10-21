# Interactive Acceptance — steps only a human can complete

Some acceptance steps **cannot** be automated: Claude Code's trust prompt is a
deliberate human gate, and PreToolUse hooks only execute in interactive
sessions (verified 2026-10, CC 2.1.x: `--print` never fires hooks).

This document is the copy-paste checklist. Items marked **PENDING** were not
yet executed on the reference machine — they are not PASS, and we do not
claim them.

> Rule: the installer and launcher never grant trust on your behalf, and
> never modify global security configuration to bypass prompts.

## 0. Automated preflight (already done by tooling)

```bash
python tools/workbench.py doctor
```

Covers: Python ≥ 3.10 · claude CLI presence/version · git · OS · target dir
state · global ECC rules presence (read-only) · existing user-level PreToolUse
hooks (read-only, duplicate-hook risk report).

## 1. First launch — trust acceptance (HUMAN ONLY, ~1 min)

1. Run the command printed by `python tools/workbench.py launch`
   (PowerShell: `launch/workbench.ps1`; POSIX: `sh launch/workbench.sh`).
2. Claude Code shows its workspace-trust prompt for the new directory.
   **Read it, then accept yourself.** This is your decision; nothing in this
   distribution can or should pre-answer it.
3. Confirm the workspace loaded: the session's context should reflect the
   workbench CLAUDE.md (ask: "what modes do you have?" — expect LEAN as the
   default and POWER as an explicit opt-in).

Status on reference machine: **PENDING** (awaiting user's first interactive launch).

## 2. Gate three-tier verification (HUMAN, ~5 min, inside the session)

Default installed mode is `audit`. Run these five probes; expected behavior
per mode:

| # | Setup | Action in session | Expected |
|---|---|---|---|
| 1 | `gate mode --set disabled` | ask it to run `git push` | no gate log entry |
| 2 | `gate mode --set audit` | ask it to run `git push` | permission prompt appears AND a decision row lands in `harness-data/gate-log.jsonl` with `"decision": "audit"` |
| 3 | `gate mode --set enforce` | ask it to run `git push` | tool call blocked (exit 2), stderr says ENFORCE |
| 4 | `gate approve --pattern "git push.*" --ttl 300`, then #3 again | ask it to run `git push` | allowed (approval active); log shows `allow` |
| 5 | corrupt `harness-data/gate.json` temporarily, mode enforce | any Bash call | blocked — **fail closed**; restore the file after |
| 6 | mode audit | read a file / list a directory (ordinary reversible tools) | normal permission behavior — no gate entries for reversible ops, no unexpected prompts |
| 7 | mode audit | **decline** the permission prompt when offered | the tool call is skipped, the session continues normally (no crash, no retry loop) |

CLI paths above are relative to the install target, e.g.
`python <target>/harness-core/harness/cli.py gate mode --set enforce`.

Status on reference machine:
- Steps 3 & 2-equivalent: **PASS** via subprocess-level hook contracts
  (26 harness-core contracts include enforce-block exit 2 and audit-passthrough).
- Steps 1–5 inside a real interactive session: **PENDING** (hooks require
  interactive mode; see header).

## 3. Cross-project rule isolation (HUMAN, ~2 min)

The launcher sets `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` as a
process env var (project-settings env blocks are not honored — verified
2026-10). In the launched session:

1. `--add-dir` a target project that has its own CLAUDE.md.
2. Ask: "which CLAUDE.md files are active?" — expect both the workbench's
   and the target's; global `rules/ecc/**` must NOT be in effect for this
   session (the workbench settings carry `claudeMdExcludes`).
3. Confirm a *different*, non-workbench Claude Code session elsewhere still
   sees your normal global rules (isolation is per-session, nothing global
   was modified).

Status on reference machine: mechanism verified via probe sessions;
full interactive confirmation **PENDING**.

## 3b. Exit recovery (HUMAN, ~1 min, after closing the session)

1. Exit the workbench session (Ctrl+C / `/exit`).
2. Confirm nothing leaked into your global state: open a plain Claude Code
   session in any other directory and ask "which CLAUDE.md files are
   active?" — expect exactly your pre-install set (the workbench adds
   itself per-session only).
3. Confirm your shell environment is unchanged: no persistent
   `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` in the parent shell
   (the launcher sets it on the child process only):
   PowerShell `$env:CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` → empty.

Status on reference machine: **PENDING**.

## 4. After acceptance

Record the outcome (one line each: date, step, PASS/FAIL, notes) in your own
tracker or append to `RELEASE_READINESS.md` under "Interactive evidence".
If any step FAILs, that is a release-blocking defect — please report it.
