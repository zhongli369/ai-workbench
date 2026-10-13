# Security Policy

## Scope and threat model

AI Workbench is a **local** orchestration layer. Its security-relevant
surfaces:

| Surface | Risk | Mitigation shipped in this RC |
|---|---|---|
| `hooks/harness_gate.py` (PreToolUse) | A shell hook that fails open would silently disable the gate | ENFORCE mode fails **closed**: unreadable/corrupt gate config blocks |
| Installer (`tools/workbench.py`) | Deleting user files on uninstall; silent global-config edits | Manifest-driven owns-only uninstall; refuses without manifest; user-scope changes are printed, never applied |
| Feedback store | Sensitive data pasted into failure records | `redact=True` strips key/mail shapes before write (contract-tested) |
| Bundled ECC snapshot | Unreviewed third-party hooks/skills | Node hook runtime NOT taken; snapshot scanned by `tools/check_hygiene.py` |
| Telemetry | Exfiltration of usage data | Ledger is a local JSONL file. **Nothing in this distribution performs network I/O.** |

Explicitly out of scope: the security of Claude Code itself, of the upstream
ECC project (report those upstream), and of the target projects you edit.

## Gate semantics — read this before trusting it

- **AUDIT mode is not a security boundary.** It logs and prompts; a malicious
  or buggy process can ignore it. Do not rely on it for protection.
- **ENFORCE mode** blocks configured patterns unless pre-approved (TTL),
  and fails closed on configuration errors.
- `claude --print` (non-interactive) does not execute PreToolUse hooks; the
  gate is an interactive-session control. Verified 2026-10 on Claude Code 2.1.x.

## Secrets

- No credentials are required to install or run this distribution.
- Tokens must travel via environment variables, never command-line arguments.
- The hygiene gate (`python tools/check_hygiene.py`) rejects common secret
  shapes in the tree; it is a lint, not a vault.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.
Contact the maintainers privately via the channel in the repository profile
(or, if none is listed, open a minimal issue asking for a private contact —
do not include details). We aim to acknowledge within 7 days.

## Supported versions

| Version | Status |
|---|---|
| 0.1.0-rc.1 | Release candidate — fixes welcome |
| anything older | not supported |
