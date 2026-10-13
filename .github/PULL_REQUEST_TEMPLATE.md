## What & why

<!-- one paragraph: the problem, the change, the evidence -->

## Contracts

- [ ] `python -m pytest tests/ harness-core/tests/ -q` passes locally
- [ ] New behavior ships with contracts in the same commit
- [ ] `python tools/check_hygiene.py` passes

## Invariants (do not break)

- [ ] No new runtime dependencies in `harness-core/`, `tools/`, `hooks/`
- [ ] harness-core does not auto-modify any user config or rules
- [ ] Negative results preserved: if a measurement got worse, the report says so

## Measurements (if performance-relevant)

| arm | before | after |
|---|---|---|
| | | |
