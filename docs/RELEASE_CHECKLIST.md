# Release Checklist

Run top to bottom before any tag. Do not skip; do not let enthusiasm edit
this list after a failure — fix the cause instead.

## 1. Contracts & hygiene (offline, ~10 s)

```bash
python -m pytest tests/ harness-core/tests/ -q          # all green
python tools/check_hygiene.py                            # no paths/secrets
python tools/check_ecc_provenance.py                     # snapshot == manifest
python -m compileall -q tools/ harness-core/harness/ hooks/
```

## 2. Install round-trip (each supported scope)

```bash
python tools/workbench.py --target <tmp> doctor
python tools/workbench.py --target <tmp> install --yes
python tools/workbench.py --target <tmp> status
python tools/workbench.py --target <tmp> benchmark
python tools/workbench.py --target <tmp> uninstall --yes --purge-data
```

## 3. ECC upstream re-verification (needs network or a fresh clone)

```bash
git ls-remote https://github.com/affaan-m/everything-claude-code HEAD
python tools/check_ecc_provenance.py --upstream <path-to-fresh-clone>
```

Decide per release: keep pin (justify in NOTICE) or bump (re-record
MANIFEST.sha256, re-run all contracts, update NOTICE + CHANGELOG).

## 4. Docs consistency

- [ ] README capability table matches `.claude/` contents (counts)
- [ ] README performance numbers match the latest RELEASE_READINESS
- [ ] CHANGELOG has an entry for this version
- [ ] No doc promises anything the contracts don't prove

## 5. Negative evidence preserved

- [ ] Unfavorable benchmarks still printed in README + RELEASE_READINESS
- [ ] Known limitations section current (hooks/--print, ECC pin, platform coverage)

## 6. Version & tag (maintainer, after human approval)

- [ ] `RC_VERSION` in tools/workbench.py bumped
- [ ] CHANGELOG version header date set
- [ ] git tag (annotated) — only after explicit human approval to publish
