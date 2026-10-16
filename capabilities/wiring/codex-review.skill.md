---
name: aiwb-codex-review
description: On-demand independent second opinion from the locally installed OpenAI Codex CLI (non-interactive, read-only sandbox). Use ONLY when the user explicitly asks "用 codex 审查" / "codex 第二意见" / "second opinion with codex" on a bounded target (a commit, branch diff, or single file). Never invoked by default; never more than one bounded review per ask.
---

# Codex second-opinion review (on-demand, default OFF)

Claude Code does primary development. Codex appears ONLY when the user explicitly
invokes this skill on a bounded target. This is a second opinion, not a production
review tool: default hooks = 0, default model calls = 0, and a Codex failure must
never affect normal Claude Code work.

## Prerequisite check (health)

The PATH `codex` on this machine is a DIFFERENT tool (npm static-site generator,
v0.2.3 — `codex build|watch|serve|skeleton`). The real OpenAI Codex CLI is a
`codex-cli` binary. Verify it exists before invoking (missing = tell the user Codex
is not available, do NOT try to install/upgrade anything):

```bash
CODEX="$(cygpath -u "$USERPROFILE")/.codex/plugins/.plugin-appserver/codex.exe"
"$CODEX" --version    # expect: codex-cli 0.<x>.-alpha.<y>  (verified: 0.162.0-alpha.2)
```

If that path is stale, fall back to the newest `codex.exe` under
`~/.codex/.sandbox-bin/` (verified older bundle: 0.150.0-alpha.12.2). The chosen
binary must respond to `--version` with `codex-cli` before any review runs.

## Verified review invocation

Bounded, non-interactive, read-only. Review ONE commit of this repo:

```bash
cd "<repo-root>"                     # review has no --cd; must run inside the repo
CODEX="$(cygpath -u "$USERPROFILE")/.codex/plugins/.plugin-appserver/codex.exe"
"$CODEX" exec review --commit <SHA> --ephemeral \
  -c sandbox_mode=read-only -c 'notify=[]'
```

Variants for the same bound scope:

- `--base <branch>` — review the diff introduced since a base branch.
- `--uncommitted` — review staged/unstaged/untracked changes (working tree must
  be genuinely dirty first; never before a snapshot).

Mandatory flags (verified against `exec --help` / `exec review --help` + a real run):

- `--commit <SHA>` / `--base <BRANCH>` / `--uncommitted` — keeps the review bounded.
- `--ephemeral` — no session files persisted.
- `-c sandbox_mode=read-only` — official read-only sandbox (approval: never).
  Never add `--dangerously-bypass-approvals-and-sandbox`.
- `-c 'notify=[]'` — skip this machine's turn-end notify hook (it points at
  `codex-computer-use.exe` and otherwise holds the process open past the answer).
- `--commit` cannot be combined with a positional prompt; the built-in review
  instructions suffice. A custom prompt is only possible with `exec` (not
  `review`) — prefer the official `review` subcommand.

## After the run (verification, always)

1. Record the exit code and wall time.
2. `git status --short` must be empty. Any change written by Codex = the
   read-only claim failed; report it and restore. Empty is the PASS bar.
3. Redirection to a temp file (outside the repo) is recommended so a long review
   does not flood the session; extract the final findings section when done.

## Scope and cost

- ONE bounded review per explicit ask. A "review the repo" without a bounded
  target is out of scope — ask which commit / file / branch.
- Each run is one model session billed to the machine's Codex provider account
  (here: deepseek via the provider's API token). Verified sample: commit review
  of ~260 diff lines ≈ 7 min wall, one model session. Do not loop.
- A single file can be reviewed without git: `git show <SHA> -- <path>` piped as
  context is NOT needed — `--commit <SHA>` already caps the diff to that commit;
  to limit further to one file, add a path filter via a plain-text instruction
  is not supported, so prefer `--commit` plus telling the user the file scope.

## Auth caveat (this machine, recorded 2026-10-16)

The provider here is `deepseek` with an inline `experimental_bearer_token` in
`~/.codex/config.toml`. The CLI formerly refused with "API key login is required,
but ChatGPT is currently being used. Logging out." when `~/.codex/auth.json`
contained a ChatGPT OAuth credential — and that login/re-login flow deletes
`~/.codex/auth.json`. So: never trigger login flows; if a review exits with the
auth-mismatch message, do NOT auto-login or fabricate credentials — report the
error honestly and let the user resolve their Codex auth. Do not read or print
any token value at any point.

## Safety boundaries

- Never use `--dangerously-bypass-approvals-and-sandbox` or `--worktree`.
- Never point Codex outside the git repo; never `--uncommitted` on a dirty tree
  you do not intend to be seen.
- No uploaded repo mass-scan: `--commit`/`--base` only.
- Never print/read `~/.codex/auth.json` or any `experimental_bearer_token`.
- Never auto-enable, auto-install, or add hooks. Enabling this capability only
  writes this skill file — nothing else.

## Turning it off

`workbench capability disable codex-review` removes the managed skill file and the
registry entry; the Codex CLI itself is untouched. Normal Claude Code behaviour is
byte-identical whether this skill exists or not — it adds zero hooks and zero
default model calls.