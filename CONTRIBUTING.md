# Contributing

Thanks for considering a contribution. This project values **evidence over
enthusiasm**: changes ship with contracts, measurements, or both.

## Ground rules

1. **Run the contracts before pushing.** All 37 must pass, offline, stdlib only:
   ```bash
   python -m pytest tests/ harness-core/tests/ -q
   ```
2. **No new runtime dependencies** in `harness-core/`, `tools/`, or `hooks/`.
   Deterministic, stdlib-only is the architecture, not an accident.
3. **No personal paths, no secrets.** `python tools/check_hygiene.py` must pass.
4. **Negative results are data.** If your change makes something worse, the
   report keeps both numbers. Never delete unfavorable history.
5. **harness-core never auto-modifies user config.** Promotions are proposals;
   a human applies them.

## What to work on

- **Good first issues**: additional clean-room scenarios (see
  `tests/test_cleanroom_install.py` for the pattern), ECC pin re-verification,
  POSIX launcher hardening.
- **Needs design discussion first** (open an issue): anything touching the
  frozen harness-core data schemas (feedback v2, promotions ledger), the gate
  decision semantics, or the installer manifest format.

## Development setup

No build step. Clone, run the contracts, done. The CI matrix
(Windows/Linux/macOS × Python 3.10–3.12) is the compatibility bar.

## Commit style

Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
One behavior change per commit; contracts in the same commit as the code.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Do not open public issues for vulnerabilities.
