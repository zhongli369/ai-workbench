---
name: aiwb-repomix
description: Pack a large repo or subtree into one LLM-friendly file with the repomix CLI (user-installed, MIT). Use ONLY when built-in search/read is genuinely insufficient — whole-repo architecture orientation, cross-cutting refactors, handing a bounded codebase snapshot to a fresh subagent. Not for routine navigation.
---

# repomix context packing (DEEP-tier tool)

## When (and when not)

- Use for: whole-repo orientation on an unfamiliar large repo; cross-cutting
  change planning where targeted Grep/Read cannot establish the blast radius;
  packing a bounded subtree for a fresh subagent's context.
- Do NOT use for: finding one symbol, reading one file, routine edits — the
  built-in tools are cheaper and fresher. FAST tasks never need this.

## Usage

```bash
repomix "<abs-path>" --output "<temp-output-file>"
repomix "<abs-path>" --include "src/**,tests/**" --output "<temp-output-file>"
```

- Always write to a temp output file and Read it selectively; never dump the
  packed content into chat wholesale.
- Respect the target's `.repomixignore` / `.gitignore`; if none exists and the
  repo may contain secrets, pack with `--include` limited to source dirs.
- Packed output is a point-in-time snapshot — re-pack after edits instead of
  trusting a stale pack.

## Safety

- Fully local CLI, no network service. Never pack credential stores, `.env`,
  key material, or `harness-data/` private feedback into output that will be
  quoted broadly.
- This skill was installed by `workbench capability enable repomix`; the CLI
  itself is user-installed and is never auto-installed.
