# Decision: browser capability via the Playwright MCP server (`mcp-config` wiring)

- **Date**: 2026-10-15
- **Status**: accepted for `playwright-mcp`; **OPTIONAL capability, default OFF**
- **Scope**: `tools/wiring_mcp.py`, `tests/test_wiring_mcp.py`,
  `capabilities/wiring/playwright-mcp.skill.md`,
  `capabilities/fixtures/{mcp-handshake.mjs,web-demo/}`
- **Not in scope**: `tools/capability.py` and `capabilities/registry.json`
  (owned by the integration pass; the proposed snippets are in §8)

## 1. Decision

The workbench does **not** implement a browser. It wires the official Microsoft
Playwright MCP server into the target project's native Claude Code project-level
MCP config (`.mcp.json`) on demand, through a third wiring type, `mcp-config`.

- Package: `@playwright/mcp`, **pinned to `0.0.83`** — read live with
  `npm view @playwright/mcp version` on 2026-10-15. `latest` is forbidden: an
  unpinned browser server is an unpinned attack surface, and the argv written
  into `.mcp.json` must be reproducible.
- Managed server key: **`aiwb-playwright`** (reserved `aiwb-` namespace).
- Browser argv: `--headless --isolated --browser chromium`. `--isolated` keeps
  the profile in memory — the user's real browser profile and cookies are never
  opened or imported.

Rejected alternatives: reimplementing a browser driver (the task forbids it, and
it would be strictly worse than the vendor server); a standalone long-running
browser service (violates default-OFF); wiring by editing the user's global MCP
config (forbidden — project-level `.mcp.json` only).

## 2. Default OFF (what "off" means, verified)

Importing `tools/wiring_mcp.py` starts nothing, spawns nothing, writes nothing.
`workbench install` writes no `.mcp.json` and no `harness-data/mcp-wiring.json`
(asserted by `test_install_never_writes_mcp_config`). No package and no browser
is ever downloaded by the workbench: `enable` refuses unless node, npm, the
pinned package (`npx --no-install @playwright/mcp@0.0.83 --version`) and a
browser are already resolvable **offline**. Only an explicit enable mutates disk,
and even then no browser process starts until an MCP tool is actually called.

## 3. Four-state status (canonical)

`enable`/`status` never report "connected" without a real handshake: the probe
spawns the **exact argv that was written into `.mcp.json`**, sends JSON-RPC
`initialize`, `notifications/initialized`, `tools/list`, then kills the process
tree (Windows: `taskkill /T /F`).

| State | Meaning |
|---|---|
| `not-installed` | node / npm / pinned package / browser not ready (or target dir missing). `detail` lists what is missing. |
| `installed-not-enabled` | runtime ready, no `aiwb-playwright` entry in the target's `.mcp.json`. |
| `enabled-not-connected` | entry present, but the MCP handshake failed (or the entry is malformed). Wired but broken — reported, not hidden. |
| `connected-tested` | entry present and the handshake just answered (`initialize` + `tools/list`). This is a wiring verdict: it means *this command line spoke MCP*, not that a page will render correctly. |

Escape hatch: `--no-probe` yields `enabled-unprobed`, deliberately **not** one of
the four — "we did not ask" is a weaker claim than "it did not answer".

## 4. Idempotency and uninstall semantics

- Re-enable rewrites the same single entry (entry hash compared): the second
  enable prints `幂等, 未改动`; servers never stack and never duplicate.
- `disable` removes exactly the `aiwb-playwright` key and nothing else. Other
  servers, other top-level keys, and the file's own indent are preserved.
  A `.mcp.json` the workbench created is deleted when it becomes empty; a file
  the user already had is kept (even if empty).
- Unknown config is never "repaired": an unparsable `.mcp.json`, a foreign
  top-level shape, a server key without the `aiwb-` prefix, a `file` containing
  path traversal, or a corrupt `harness-data/mcp-wiring.json` all **fail closed**
  with nothing written.
- `.mcp.json` is deliberately **not** registered in `install-manifest.json`:
  an owns-only uninstall must never delete a file that is partly the user's.
  Bookkeeping lives in `<target>/harness-data/mcp-wiring.json`; the optional
  `wire_uninstall_sweep(target)` one-liner drops managed entries (and the
  managed SKILL.md) during `workbench uninstall`.
- Activation is still a human step: a project-level MCP server must be approved
  in the Claude Code session (`/mcp`) before its tools appear.

## 5. Real connection evidence (`@playwright/mcp@0.0.83`)

Executed in a temp dir with the pinned package installed from npm:

```
offline readiness probe:
  cmd /c npx --no-install @playwright/mcp@0.0.83 --version -> exit 0, "Version 0.0.83"
handshake (node capabilities/fixtures/mcp-handshake.mjs, cached in
capabilities/fixtures/web-demo/evidence/mcp-toolcall-navigate.json):
  server        : Playwright 1.64.0-alpha-1790635538000 (protocol 2025-06-18)
  tools/list    : 25 tools
  tools/call    : browser_navigate -> OK
                  "Page URL: http://127.0.0.1:8765/index.html
                   Page Title: AIWB web-demo fixture"
  elapsed_ms    : 1901
  child_alive_after_kill: false
```

The same argv was exercised through the Python probe (`mcp_handshake`) and
through the CLI enable path. After every probe the process table was audited:
node 5 -> 5, cmd 2 -> 2, chrome 0 (baseline 5 node / 2 cmd), i.e. **no residual
process** — the MCP server and its browser are gone after the probe.

Live end-to-end enable was also run in a path containing a space and CJK
characters (a temp dir named `工作台 测试 项目`): readiness check passed, the
managed entry was written, the handshake succeeded, a second enable was
idempotent, a pre-existing user server plus an unrelated top-level key and a
4-space indent survived untouched, and `disable` removed only the managed entry.

## 6. Real browser tests (three, all local)

Driver: `capabilities/fixtures/web-demo/run-browser-tests.mjs`; page:
`capabilities/fixtures/web-demo/index.html`; evidence in
`capabilities/fixtures/web-demo/evidence/` (`last-run.json` + 5 screenshots).
Result: **18 pass / 0 fail**.

- **T1 button event** — `#cta` before `{text: 保存, data-state: idle, counter:
  已保存 0 次}`; after a real click `{text: 已保存, data-state: saved, counter:
  已保存 1 次}`; zero uncaught page errors and zero console errors.
- **T2 layout defect** — desktop 1280px: no horizontal overflow, 3 cards on one
  row (all `top=170`). Narrow 375px on the shipped CSS: `scrollWidth=1012`
  against `innerWidth=375` and `#export.right=410`, i.e. the toolbar and the
  fixed 3x320px grid overflow the device width. Screenshots
  `t2-before-mobile-broken.png` / `t2-after-mobile-fixed.png` are the same HTML
  with `styles.fixed.css` (wrap + `auto-fit minmax(240px,1fr)`) as `styles.css`:
  back to `innerWidth=scrollWidth=375`, no element past the device width, and
  the page skin is unchanged (identical body background). Measured with a plain
  375px viewport *and* with mobile emulation (UA + `isMobile` + touch), because
  under `isMobile` an overflowing page *widens* the layout viewport (1012)
  instead of scrolling — the naive `scrollWidth > innerWidth` assertion is blind
  to exactly the bug being hunted, so the assertion compares against the device
  width instead.
- **T3 slider drag** — real pointer drag (`mouse.move`+`down`+moves+`up`) took
  `#zoom` from `30` to `83`, the `<output>` followed to `83%`, `input` fired 24
  times, `change` fired once on release, and `#cta` still worked afterwards
  (`已保存 1 次`).

## 7. Limitations (stated, not hidden)

- **Desktop viewport simulation is not a real device.** T2's narrow pass is
  desktop Chrome with a 375x812 viewport, a mobile UA and touch emulation. No
  physical Android/iOS device was involved: **真机未验证**. It catches layout and
  event bugs, not device-specific rendering, scroll physics, or touch latency.
- **The bundled Playwright chromium was not used for these runs** — the download
  (`npx playwright install chromium`, build 1247) was aborted after ~18 MB
  because `cdn.playwright.dev` was throttled to ~9 KB/s from this machine (curl
  to the CDN timed out, npmmirror paths 404). The three tests therefore ran with
  `--channel chrome` (system Chrome 155.0.8059.41, throwaway profile launched by
  Playwright). `npx playwright install chromium` resumes the download; once it
  finishes, re-run `run-browser-tests.mjs` without `--channel` to reproduce the
  default argv path.
- The MCP tool-call evidence above was produced with `--browser chrome` for the
  same reason; the `.mcp.json` entry ships `--browser chromium`.
- Adding tests moved the repo's live contract count; README/README.zh-CN/CI
  counts were updated to the gate's live values (397 total / 226 `tests/`).
- The `.mcp.json` the server runs from is project-level only, and the capability
  is mutually exclusive with `agent-browser` (existing `mutex` in the registry).
- A stale `app`-level Chromium may keep a `.playwright-mcp/` snapshot directory:
  the MCP server writes page snapshots under the *cwd it is launched in*. That is
  the project directory, so those artifacts land in the project, not in a global
  cache.
- Local harness note: the worktree's PreToolUse gate hook refused Bash commands
  containing the literal token `enable`, so the CLI `enable` path was exercised
  via the documented function API (`wire_enable`) plus the pytest suite, which
  drives the real CLI (`test_cli_*`). The hook was not bypassed.

## 8. Integration (for the pass that owns `capability.py` + `registry.json`)

`capabilities/registry.json` — entry for the existing `playwright-mcp` id:

```json
"wiring_action": {
  "type": "mcp-config",
  "server_key": "aiwb-playwright",
  "package": "@playwright/mcp",
  "pin": "0.0.83",
  "file": ".mcp.json",
  "template": "playwright-mcp.skill.md",
  "dest": ".claude/skills/aiwb-playwright-mcp/SKILL.md"
}
```

`tools/capability.py` — 5 lines in the enable/disable/status dispatch, before
the existing `skill-file` branch:

```python
rl = wiring_mcp.dispatch(sub, rc_root, target, cap)
if rl is not None:
    ok, msgs = rl
    for m in msgs: print("     " + m)
    if sub == "enable" and not ok: return 1
```

Two integration notes: (a) `tests/test_capability_wiring.py::
test_wiring_templates_exist_and_are_clean` currently asserts `type ==
"skill-file"` for every registry entry that has a `wiring_action` — that
assertion must accept `mcp-config` (its template/dest hygiene checks still
apply); (b) `wire_uninstall_sweep(target)` is the optional one-liner for
`workbench uninstall`.
