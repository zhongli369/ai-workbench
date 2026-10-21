# Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  ONE launched Claude Code session (the workbench)               │
│                                                                 │
│  CLAUDE.md (LEAN session policy, 83 lines)                      │
│   ├─ safety invariants (verify before done, no secrets, gate)   │
│   ├─ multi-project protocol + explicit-plugin rules             │
│   └─ capability INDEX only — bodies load on demand              │
│                                                                 │
│  ┌───────────────┐  ┌────────────────┐  ┌────────────────────┐  │
│  │ 11 skills     │  │ 1 agent        │  │ 14 commands        │  │
│  │ (curated set) │  │ (on demand)    │  │ (on demand)        │  │
│  └───────────────┘  └────────────────┘  └────────────────────┘  │
│     ▲ curated subset (MIT, pinned snapshot, vendor/ecc);        │
│     ▲ 19 skills + 15 agents kept disabled (workbench/disabled/) │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ harness-core (self-developed, stdlib, 253 contracts)      │  │
│  │  feedback store ── query ── report ── promote (human)     │  │
│  │  gate: disabled / audit / enforce (fail-closed)           │  │
│  │  telemetry ledger (local JSONL, zero network)             │  │
│  └───────────────────────────────────────────────────────────┘  │
│     ▲ PreToolUse hook (harness_gate.py; Bash|PowerShell)        │
└─────────────┬───────────────────────────────────────────────────┘
              │ absolute paths / git -C / python -m pytest <dir>
    ┌─────────┴──────────┬──────────────────┬────────────────┐
    ▼                    ▼                  ▼                ▼
┌─────────┐        ┌──────────┐      ┌──────────┐     ┌──────────┐
│ project │        │ project  │      │ project  │     │ project… │
│ A       │        │ B        │      │ C        │     │          │
│ own     │        │ own      │      │ own      │     │ never    │
│ CLAUDE. │        │ CLAUDE.  │      │ CLAUDE.  │     │ modified │
│ md wins │        │ md wins  │      │ md wins  │     │ by us    │
└─────────┘        └──────────┘      └──────────┘     └──────────┘
   per-project failure memory namespaced by project_id — no cross-leak
```

## Layers, and why they exist

| layer | install unit | purpose | can be used alone? |
|---|---|---|---|
| harness-core | `harness-core/` | failure memory, gate, telemetry | **yes** — plain CLI, no Claude Code needed |
| workbench | `.claude/` + CLAUDE.md + launch | CC workspace config, session policy, capabilities | yes (without harness it just lacks memory/gate) |
| combined | full install | the intended product | — |

## Data flow of the failure-memory loop

```
session A: failure occurs
   → record (source: user-correction | human-verified | model-inference)
   → JSONL append (candidate)
   → [human review] promote → verified/promoted
session B: an observed failure occurs (fail-triggered — never on a fresh task)
   → query --keyword → ranked by source authority
   → apply the mitigation, not the same retry
   → record outcome
weekly: report → recurring causes → promotion PROPOSALS (never auto-applied)
```

## Trust boundaries

- Nothing in this distribution performs network I/O.
- The gate is a PreToolUse hook; `claude --print` does not execute hooks
  (verified 2026-10, CC 2.1.x) — enforcement exists in interactive sessions.
- AUDIT mode is observability, never protection; ENFORCE fails closed.
- Uninstall deletes only manifest-listed files; `harness-data/` survives
  unless `--purge-data`.
