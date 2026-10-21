# Capability Evidence Register (2026-10-14; ARSENAL additions 2026-10-15; R5/R7 status sync 2026-10-21)

Directive §5 product-value audit: what AI Workbench adds over native Claude
Code + ECC, judged only on recorded evidence. Every enhancement lists its
trigger condition, real invocation evidence, user value, measured cost,
opt-out, and default state. N=1 cells are exploratory, never advertised as
stable advantages.

## 1. Origin honesty (what is NOT ours)

| Capability | Origin | Workbench's role |
|---|---|---|
| Edit / test / ship loop, tool use, planning | **Claude Code native** | none — not counted as our value |
| 60+ agents / 240+ skills catalog, rules | **ECC upstream** (MIT) | curated subset (11 skills / 1 agent / 14 commands active; a further 19 skills + 15 agents kept disabled under `workbench/disabled/`), pinned snapshot, on-demand loading |
| Workspace snapshot algorithm (`harness snap`) | **cline@789f79e4** (Apache-2.0) | reimplemented stdlib-only (no vendored code); safety rules redesigned per directive (never `reset --hard` / `clean -fd`) |
| Post-edit verify loop (`harness verify`) | **aider@5dc9490b** (Apache-2.0) | reimplemented stdlib-only; gate-consulted, bounded reflections |
| Supply-chain scanning (release gate) | **trivy** (Apache-2.0, binary fetched at CI time, never vendored) | pinned version+sha256 wrapper with honest exit semantics |
| Everything else below | **Self-developed** | — |

Self-developed: harness-core (feedback store, gate, report, telemetry,
checkpoints, plan scaffold, verify loop, workspace snapshots), release
supply-chain gate, installer/launcher/uninstaller,
FAST/STANDARD/DEEP cost policy (retired in R5), capability registry +
wiring, bench infrastructure (internal).

## 2. Mechanism-by-mechanism evidence

### Oracle (repeat-error retrieval) — **EXPERIMENTAL / ON-DEMAND (final)**

- **Trigger**: fail-triggered (query before debugging an *observed* failure;
  never by default on a fresh task).
- **Real invocations across 6 controlled seeded experiments** (r4b, e4o, t3b,
  t6.1, plus two earlier pairs): **0 queries on every seeded arm**. The model
  self-diagnosed every time because every task's root cause was readable
  inside the workspace. t8: 0 queries — the one real agent failure (corrupted
  checkpoint hash) was silent, so nothing observable existed to trigger on.
- **User value**: mechanism verified (record→store→query→isolation, 64
  harness-core contracts); **retrieval payoff unproven in vivo**.
- **Cost when it does fire**: ≈$0.34 on an empty store (g2/g2b pair,
  exploratory). On green-run tasks: $0.00 (never fires).
- **Opt-out**: on-demand only; nothing in the default path queries it.
- **Mis-trigger risk**: none observed (six zero-query arms).
- **Product status**: removed from headline value propositions; documented as
  experimental. Not removed (no measured cost harm); not upgraded (no
  attributable benefit). The unbuilt structural-nudge proposal stays unbuilt.

### Gate (three-tier irreversible-command control) — **DEFAULT ON (AUDIT)**

- **Trigger**: every PreToolUse Bash/PowerShell call in interactive sessions
  (ENFORCE blocks configured high-risk patterns unless pre-approved).
- **Evidence**: structural — 64 harness-core contracts (fail-closed on
  unreadable config; AUDIT never consults tokens; one-time `awt-` tokens
  single-use/TTL/replay-safe). Interactive acceptance (G8) is user-pending.
- **User value**: irreversible commands become deliberate acts; AUDIT gives
  an audit trail with zero blocking.
- **Cost**: local hook execution only; no model tokens.
- **Opt-out**: `gate mode` DISABLED/AUDIT/ENFORCE.
- **Mis-trigger risk**: ENFORCE false-blocks possible on pattern matches —
  mitigated by one-time approvals; AUDIT (default) cannot block.
- **Known limit**: `claude --print` does not execute hooks (verified CC 2.1.x).

### On-demand ECC capabilities — **DEFAULT ON (passive)**

- **Trigger**: the model loads a skill/agent when the task calls for it.
- **Evidence**: 0 skill/agent invocations across all 21 paid bench sessions
  (batches 1–5) on green-run tasks — the harness is a free option: it costs
  nothing when not needed. t7 (deep refactor) still made 0 calls.
- **User value**: curated expert knowledge available without the ≈20.7k-char
  resident rule tax (L0+index ≈9.0k chars, −57%; L0 alone −92%).
- **Opt-out**: capability registry (`enable`/`disable`), per-scope install.
- **Product status**: verified structural benefit (resident-context
  reduction); task-level superiority NOT established (t7: no measurable
  tax or benefit, N=1).

### Recovery (fail-triggered diagnosis flow) — **DEFAULT ON (policy)**

- **Trigger**: an observed failure.
- **Evidence**: t6.1 — all four arms recovered from the external-config-drift
  failure in ≤15 turns (PASS). The recovery came from the model reading
  workspace evidence, not from any harness component — the harness's role was
  the policy that says *diagnose before retrying*, plus zero oracle cost.
- **Cost**: none measured (t6.1 fusion-empty $0.0726 ≈ native $0.0892).
- **Product status**: the policy is sound; it is not a moat.

### FAST/STANDARD/DEEP cost policy — **RETIRED (R5, 2026-10-20)**

- **Evidence**: trivial 0.87× / multi-file feature 0.84× / bugfix 1.22× /
  test-diagnosis 1.81× (all N=1). Mixed but honest; the 1.22× residual is
  turn-count behavior, tracked as G4.
- **Product status**: **removed from the session payload in the R5
  slim-down** (LEAN default; controlled harness-bench runs later showed heavy
  default injection netting negative, SE family -0.486). Kept here as
  historical record; the current session policy is `workbench/CLAUDE.md`.

### Planning / agent routing — **NOT EVIDENCED**

- **Real invocations**: 0 across all paid bench sessions. These are
  Claude-Code-native behaviors the workbench does not override; no
  workbench-specific planning/routing component has fired in vivo.
- **Product status**: not advertised. (The TOTAL FUSION `harness plan`
  scaffold below is a *deterministic* on-demand CLI, not a routing layer.)

### Checkpoints (t8-class state integrity) — **NEW, DEFAULT ON (on-demand CLI)**

- **Trigger**: long-horizon / multi-session work — explicit
  `harness checkpoint begin/save/load/verify/list`; `harness plan --save`
  writes the stage-0 record.
- **Origin**: TOTAL FUSION Batch 1, replacing SystemKernel's
  `FileCheckpointStore` (its `load_latest` returned silent `None` on a torn
  tail — damage indistinguishable from absence). Kept: append-only JSONL +
  crash marker + lineage. Fixed: explicit health reports, per-record payload
  sha256, schema versioning, BOM/CRLF tolerance, atomic marker writes.
- **Evidence**: structural — 19 contracts (roundtrip, torn tail, corrupt
  middle line, hash mismatch, unknown schema, BOM, CRLF, pure-ASCII disk
  bytes, crash-marker lifecycle, chain breaks, non-monotonic stages, CLI
  exit codes incl. `verify` exit 1 on damage).
- **Cost**: zero resident; stdlib file I/O only.
- **Honest limit**: single-process writer; multi-process concurrent append
  not stress-tested.

### Plan scaffold (DEEP-mode phases + AC) — **NEW, ON-DEMAND CLI**

- **Trigger**: DEEP tasks only, explicit `harness plan "<task>"`; NEVER
  auto-injected, never a required step.
- **Origin**: TOTAL FUSION Batch 3 — minimal extraction of the retired
  CodeLike planning kernel (0 external pulls upstream). Kept: 13-archetype
  bilingual classifier, phase templates, static per-phase risk, per-archetype
  AC. Dropped: feedback-adaptation path (native oracle already covers it —
  would be a second, duplicate failure-memory), prompt factory, regex
  enrichment, project-scan coupling.
- **Evidence**: structural — 37 contracts (classification incl. the verbatim
  precedence traps, phase/risk/AC shape, determinism, ASCII serializability,
  `--save` checkpoint wiring).
- **Cost**: zero resident, zero model tokens (pure stdlib, deterministic).
- **Honest limit**: template phases are scaffolds, not task understanding;
  value is structure + resumability, not intelligence.

### Telemetry — **DEFAULT ON (local, self-excluding)**

- **Evidence**: structural — reader commands never logged; every row carries
  a source label (`cli`/`bench`/`synthetic`); bench traffic can never
  masquerade as product usage (contract-locked).
- **Cost**: none (local JSONL).

### Workspace file snapshots (`harness snap`) — **NEW, ON-DEMAND CLI (ARSENAL)**

- **Trigger**: explicit `harness snap save/list/diff/verify/restore/prune`;
  restore is dry-run by default and writes nothing until `--apply` (an
  explicit operator act that also consults the gate).
- **Origin**: OPERATION ARSENAL agent A — git-backed snapshots adapted from
  cline@789f79e4 (Apache-2.0), reimplemented stdlib-only. The directive's
  absolute boundary is encoded in the design: **never** `git reset --hard` /
  `git clean -fd`; writes are restricted to the snapshot's managed file set
  via `checkout-index`; unknown untracked files are never deleted.
- **Evidence**: structural — 24 contracts. Real acceptance on a live repo:
  deleted + corrupted files restored sha256-byte-exact; unknown scratch file
  survived untouched; a rescue ref (`refs/harness/restore-tx/<txid>`) was
  created *before* any write; a three-way concurrent edit (snapshot ≠
  baseline ≠ current) fails closed as `conflict` and the user's newer work
  is never silently overwritten; dry-run reports status `planned`, never
  `restored`.
- **User value**: agent edits become reversible without destructive git
  operations; "Agent 修改失败不会导致原本不相关的用户数据丢失" is the
  acceptance standard this mechanism is built to.
- **Cost**: zero resident; local git plumbing only, no model tokens.
- **Opt-out**: on-demand only; nothing snapshots automatically.
- **Mis-trigger risk**: interrupted restore is detected via a journal and
  reported, not silently resumed; manifest chain is sha256-verified
  (`snap verify` exit 1 on damage).
- **Honest limit**: git-backed — a non-git working tree gets an explicit
  `skipped`, not a snapshot.

### Post-edit verification loop (`harness verify`) — **NEW, ON-DEMAND CLI (ARSENAL)**

- **Trigger**: explicit `harness verify run` after an edit stage; commands
  come from a pre-authorized `.harness-verify.json` or an explicit `--cmd`
  that is gate-consulted (DISABLED refuses fail-closed; AUDIT logs+allows;
  ENFORCE consumes a one-shot `awt-` token).
- **Origin**: OPERATION ARSENAL agent B — bounded post-edit verify adapted
  from aider@5dc9490b (Apache-2.0), reimplemented stdlib-only. Reflections
  are bounded (default 3, hard cap 10); there is no unbounded auto-retry and
  no hidden model call.
- **Evidence**: structural — 26 contracts. Real acceptance: a broken config
  made `verify run` fail (exit 1, `can_claim_done` false); after
  `snap restore --apply`, the same command passed (exit 0). `verify status`
  is the mechanical completion gate: a stage whose latest verdict is not
  `pass` **cannot be claimed done**; failures write `status="failed"`
  checkpoints carrying the failed command + output preview.
- **User value**: "未通过验证就不能被系统标记为 VERIFIED" — done-ness becomes
  a mechanical fact, not a claim (the Silent-Exit Guard made executable).
- **Cost**: zero resident; argv-only subprocess execution, output truncated,
  verdicts appended to a sha256 evidence log.
- **Opt-out**: on-demand only; nothing runs automatically.
- **Mis-trigger risk**: `skipped` (no configured command) is exit 3 — never
  conflated with pass; readers (`verify status`) are never telemetry-logged.
- **Honest limit**: verifies only what the operator configured; it is a
  gate on claims, not a proof of correctness.

### Release supply-chain gate (`security.yml` + `security_scan.py`) — **NEW, CI-ONLY (ARSENAL)**

- **Trigger**: CI only — blocking on push to main / `v*` tags /
  release-published / PR-to-main; AUDIT on schedule, non-main PRs, and
  `audit_only` dispatch. Zero daily-session or FAST-path overhead.
- **Origin**: OPERATION ARSENAL agent C — trivy-class supply-chain gate.
  The trivy binary is pinned by version + sha256 (GitHub's server-side
  digest over TLS-verified `api.github.com`) and fetched at CI time — never
  vendored; all actions pinned by commit SHA; no third-party scanning
  action runs in our token scope.
- **Evidence**: structural — 24 contracts (fake-trivy JSON parsing incl.
  positive secret detection, license fallback, `.securityignore`
  expire-aware exceptions, redaction). Local run without the binary:
  exit 3 `infra-failure` — **never** read as PASS; `--licenses` fallback
  exit 0. First live blocking CI run happens with this release's PR.
- **User value**: release artifacts cannot ship with known secret-shaped
  findings or scanner infra failures silently downgraded; "扫描未完成"
  and "未通过" are distinct, explicit states.
- **Cost**: CI minutes only; zero local tokens, zero resident hooks.
- **Opt-out**: AUDIT mode for non-release refs; release path is never audit.
- **Mis-trigger risk**: matched secret text is never logged (counts only in
  step summary; parsed report goes to a private artifact); tests use fake
  scanner output — no real secrets are ever used.
- **Honest limit**: a scanner is only as current as its pinned DB; the gate
  proves "scanned, honestly reported", not "no vulnerabilities exist".

## 3. Defaults decision (directive §5C)

| Enhancement | Default | Rationale |
|---|---|---|
| Gate AUDIT | **on** | zero token cost, safety observability; ENFORCE is user's choice |
| On-demand ECC index | **on (passive)** | zero cost until used; resident tax avoided |
| FAST/STANDARD/DEEP | **retired (R5)** | removed from the session payload; LEAN default now |
| Oracle | **on-demand only** | 6 experiments, 0 real reads; no attributable benefit |
| Planning/routing extras | **absent** | native CC behavior suffices; nothing to default |
| Telemetry | **on (local)** | self-excluding; powers the failure-pattern report |
| Checkpoints | **on-demand CLI** | zero resident cost; long-horizon integrity, t8 lesson encoded |
| Plan scaffold | **on-demand CLI** | zero resident, zero model tokens; DEEP-only by policy |
| Workspace snapshots | **on-demand CLI** | reversible edits without destructive git; dry-run default, `--apply` gated |
| Verify loop | **on-demand CLI** | done-ness made mechanical; bounded reflections, fail-closed `--cmd` |
| Supply-chain gate | **CI-only, blocking on release refs** | zero daily overhead; honest exit semantics (3 ≠ PASS) |

## 4. The honest one-liner

AI Workbench today = **governed safety (command gate + reversible snapshots +
mechanical done-ness + release supply-chain gate) + curated on-demand
capabilities + low resident cost + honest engineering evidence**. Memory
retrieval and complex-task superiority are open bets, labeled as such — not
sold as facts.
