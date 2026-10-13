# Examples

## noter — the failure-reuse demo (reproducible, offline)

`noter/` is a 60-line note-taking CLI with **two seeded, independent defects**
and a deterministic acceptance checker. It exists so you can watch the
workbench's failure memory do its job in about five minutes.

```
examples/noter/
  ISSUES.md       ← the two defect reports (FC1 durability, FC2 cache)
  noter/          ← the buggy package
  selfcheck.py    ← acceptance: python selfcheck.py --task durability|cache
  notes.json      ← seed data
```

Verify the bugs are real (both must FAIL before you start):

```bash
python examples/noter/selfcheck.py --task durability   # FAIL (expected)
python examples/noter/selfcheck.py --task cache        # FAIL (expected)
```

### Walkthrough

1. **Fix it through the workbench.** Launch the workbench, then ask it:
   *"Fix the two defects in examples/noter (see its ISSUES.md); both
   selfcheck tasks must pass."*

2. **Record the failure context** when something goes wrong along the way
   (the workbench's experience-capture skill does this; manually):
   ```bash
   python harness-core/harness/cli.py feedback record \
     --project-id noter-demo --cause stale_cache \
     --summary "list cache not invalidated after add" \
     --source human-verified --confidence 1.0
   ```

3. **Next session, same error class** — query before retrying:
   ```bash
   python harness-core/harness/cli.py feedback query \
     --project-id noter-demo --keyword cache --json
   ```
   The past cause and fix surface before you pay for the same debugging twice.

4. **Promotion is human-gated.** When a cause recurs, `report` proposes it;
   nothing is ever auto-applied to rules or config:
   ```bash
   python harness-core/harness/cli.py report --project-id noter-demo
   ```

This demo is exactly what the CI and the 37 offline contracts exercise; no
network, no Claude Code login, no model calls required.
