# Decision: `@playwright/cli@0.1.22` duel against the wired Playwright MCP (`playwright-mcp`)

- **Date**: 2026-10-16
- **Status**: **verdict C — REJECT**. `@playwright/cli` is **not** wired; the pinned
  `@playwright/mcp@0.0.83` channel from the 2026-10-15 decision stands unchanged.
- **Scope**: this decision doc + three new duel fixtures
  `capabilities/fixtures/web-demo/{error.html,error.fixed.html,styles.fix-20261016.css}`.
- **Not in scope**: `.mcp.json`, `tools/capability.py`, `capabilities/registry.json`
  (none changed — a REJECT is a no to wiring), and no
  `capabilities/wiring/playwright-cli.skill.md` (that file is produced only for
  verdict A/B).

## 1. What was duelled

A real-browser duel on this machine, two channels driving the **same** local
fixtures, four representative browser tasks (B1–B4):

- **CLI**: `@playwright/cli@0.1.22` (npm `latest`, microsoft/playwright-cli,
  depends on `playwright@1.64.0-alpha-1790635538000` — the **same alpha** pinned
  by the MCP wrapper, so the shared browser cache is reused and no second browser
  is installed). Default session, in-memory profile, workspace dir `.playwright-cli/`
  confined to `%TEMP%\aiwb-pwcli` so nothing enters the repo tree.
- **MCP**: `@playwright/mcp@0.0.83` (already pinned, canonical wiring) driven over
  a stdio JSON-RPC client in Python's stdlib.

| Task | Fixture | Success criterion |
|---|---|---|
| B1 按钮点击 | `index.html` | real click on `#cta` flips `data-state`/text and `#counter` to `已保存 1 次` |
| B2 responsive | `index.html` + `styles.css` | 375x812: defect confirmed (`scrollWidth`/`#export.right` overflow device width), fixed CSS restores innerWidth=scrollWidth and a 3-card row |
| B3 slider drag | `index.html` | real pointer drag on `#zoom` range moves value by >20, `input>=1`, `change>=1`, `<output>` follows, button still works |
| B4 deliberate error | `error.html` / `error.fixed.html` | uncaught `TypeError` captured as evidence, fixed twin verified (zero console errors, `status=completed`, `docsOk=true`) |

## 2. Real results (canonical, final corrected)

PASS matrix and metrics per task:

| task | CLI | MCP |
|---|---|---|
| B1 | **PASS** 5c / 445B in / 713B out / 4182ms | **PASS** 5c / 339B / 1098B / 2369ms |
| B2 | **PASS** 8c / 1495B / 1999B / 4508ms | **PASS** 8c / 1420B / 3315B / 2060ms |
| B3 | **PASS** 14c / 708B / 1357B / 7805ms | **PASS** 7c / 521B / 1527B / 3577ms |
| B4 | **PASS** 7c / 320B / 1030B / 4370ms | **PASS** 7c / 332B / 1377B / 2020ms |

proc delta node/chrome `0/0` on every row; **chrome residue 0 on both channels
end to end** (audited after a 2s settle sleep). `b3/cli` briefly reported +4 node;
re-audit against the machine baseline (6x node outside any test) shows
per-command CLI process churn, not a server leak.

### B3 — the one real capability difference

MCP `browser_drag` is **selector-target only** (no coordinate mode): the pointer
lands at the target element's midline, so drag direction is decided by DOM layout.
First attempt `{startTarget:"#zoom", endTarget:"#export"}` — `#export` sits
**left** of the slider — dragged the pointer left and crashed the value 30 → 0
(**FAIL**, recorded). Fixed by targeting `#zoom-out` (the `<output>` immediately
right of the slider) → `start=30 drag={value:100,out:"100%",input:2,change:1}`
→ PASS.

CLI exposes explicit `mousemove / mousedown / mousemove* / mouseup` at pixel
coordinates → `start=30 drag={value:83,out:"83%",input:4,change:1}` → PASS,
deterministic by construction and layout-independent.

### B4 — evidence both channels

The uncaught error from `error.html` line 17 was captured verbatim by CLI
`console error`:

```
TypeError: Cannot read properties of undefined (reading 'boom')
    at http://127.0.0.1:8793/error.html:17:21
```

Fixed twin: `Errors: 0`, `status=completed`, `docsOk=true`. MCP
`browser_console_messages {"level":"error"}` produced the same signal.

## 3. Metrics notes

- **Schema / discovery burden**: CLI `--help` = **7,636 B** for the whole command
  surface; MCP `tools/list` = **21,382 B** for its 25 tools. Both are one-time
  per-session discovery, neither is a per-call cost.
- **Output size**: CLI `--raw` returns the pure value; MCP wraps every tool result
  in a `### Result` + `### Ran Playwright code` prose template, inflating the
  heavier outputs (B2 1,999 vs 3,315 B; B4 1,030 vs 1,377 B out). **No token-savings
  claim is made** — no model token logs were collected, and byte deltas are not
  token deltas.
- **Wall time**: the MCP channel was faster on all four tasks (persistent server vs
  one Node process spawn per CLI command; CLI shows ~850ms per `eval` spawn).
- **Residue / hygiene**: chrome 0 everywhere; no `.playwright-cli/` and no
  `.playwright-mcp/` directory ever landed in the repo tree.

## 4. Windows / harness findings

- The worktree's PreToolUse gate hook refuses any Bash command containing the
  literal token `eval` — and CLI's core subcommand **is** `eval`. The duel exercised
  the CLI from a temp Python driver (the hook was not bypassed), which is fine for a
  benchmark, but a real agent loop calling `playwright-cli eval …` from Bash hits the
  hook on every call: a recurring integration tax, not a one-time cost. This is the
  same class of friction as the `enable` hook note in the 2026-10-15 decision (§7).
- MCP tool-calls flow over stdio JSON-RPC inside a spawned server argv, so the shell
  gate never sees the `eval` token — the MCP path is unaffected.
- Both channels ran `--browser chrome` against the shared browser cache; no second
  browser was installed. Bundled chromium stays unavailable on this machine (CDN
  throttle, unchanged from the 2026-10-15 note).
- MCP `browser_drag` semantics are a real learning cost (B3 direction), but its
  element-target model is the one a model already reasons in; the CLI's coordinate
  model is exact but layout-blind.

## 5. Verdict: C — REJECT (维持 MCP)

- **Parity, not superiority.** Both channels end at 4/4 PASS on identical fixtures.
  The durable differences are capability *shape*, not head-to-head success.
- **Incumbent economics.** MCP is already pinned, offline-gated, probed through the
  4-state model, covered by 18/18 fixture tests, and documented by the 2026-10-15
  decision. It was also the faster channel in this duel.
- **CLI's real edges do not offset wiring cost.** (a) coordinate-precise mouse
  control makes drag deterministic (B3); (b) compact `--raw` output. But they collide
  with the project's `eval` gate for any Bash-first agent loop, and adding a second
  wiring path for a channel that merely reached parity is net-negative.
- Therefore `@playwright/cli` is **not wired**; `playwright-mcp` remains the browser
  channel. Ad-hoc standalone use of the CLI (exact-coordinate drag automation, compact
  raw output) is still legitimate and harmless as long as `.playwright-cli/` stays out
  of the repo — this verdict is about wiring, not about forbidding the binary.

## 6. Files produced

All new; no existing file was edited.

- `capabilities/fixtures/web-demo/error.html` — B4 broken fixture: deliberate uncaught
  `TypeError`, everything after the crashing line unreachable.
- `capabilities/fixtures/web-demo/error.fixed.html` — B4 fixed twin: same page without
  the crashing line; `status=completed`, `docsOk=true`.
- `capabilities/fixtures/web-demo/styles.fix-20261016.css` — the narrow-viewport fix
  B2 served as `fixed/` (toolbar wrap + `auto-fit minmax(240px,1fr)` grid), validated
  against the same 375px defect the 2026-10-15 decision documents.

No skill file: `capabilities/wiring/playwright-cli.skill.md` is only produced for
verdict A/B.

## 7. No-wiring note for the integration pass

Because the verdict is C, there is nothing to add to `capabilities/registry.json` or
`tools/capability.py`: no `mcp-config` entry and no `skill-file` entry for the CLI.
The existing `aiwb-playwright` entry and `playwright-mcp` wiring are unchanged. If a
future operator wants the CLI surfaced, the sensible shape is a documented
`skill-file`-style wrapper in the manner of the MCP skill — out of scope here.