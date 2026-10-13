---
name: aiwb-agent-browser
description: Drive a real browser via the agent-browser CLI (user-installed, Apache-2.0) for UI acceptance and E2E evidence — launch the app, click, assert DOM/console/network, capture screenshots. Use when a task requires real-browser verification that static checks cannot provide.
---

# agent-browser UI acceptance (STANDARD+/DEEP tool)

## When (and when not)

- Use for: verifying a web app actually works — page loads, flows complete,
  DOM assertions, console error checks, screenshot evidence.
- Do NOT use for: reading docs or static pages (plain fetch is cheaper), or
  any site you are not authorized to drive.

## Usage pattern

```bash
agent-browser open "<url>"
agent-browser click "<selector>"
agent-browser assert "<selector-or-condition>"
agent-browser screenshot "<output-file>"
```

(Exact subcommands depend on the installed version; `agent-browser --help`
is the authority. Keep sessions short and close them when done.)

## Evidence rules (learned the hard way)

- Never trust a loading-state screenshot: wait for the real content selector
  (a table header matching is NOT the tbody having rendered), then capture.
- Record console errors and failed network requests as part of the result,
  not just the final DOM.
- Restart the backend under test before asserting on new code — stale
  processes are the top cause of false failures.

## Safety

- Local Chrome for Testing, no telemetry. Mutually exclusive with
  playwright-mcp in this workbench (enable one, not both).
- This skill was installed by `workbench capability enable agent-browser`;
  the CLI itself is user-installed and is never auto-installed.
