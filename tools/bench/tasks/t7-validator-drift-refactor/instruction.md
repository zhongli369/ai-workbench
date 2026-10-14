<!-- canary:AIWB-26B-8c2d47a1e905/t7 -->

`confcfg` is a small config CLI package in this workspace. Two copies of its
validation logic were made a while ago and have **drifted apart**: depending
on which code path you hit, the same config is accepted or rejected.

The authoritative behavior is written down in `spec.md`.

Your job:

1. Unify the validation behavior so EVERY code path follows `spec.md`.
2. Remove the duplication — there must be exactly one canonical
   implementation of the validation rules (how you structure that is up
   to you).
3. Keep the public API compatible: `confcfg.load_config`,
   `confcfg.validate_config`, `confcfg.dump_config` keep their current
   signatures, and the CLI (`python -m confcfg check|normalize <file>`)
   keeps working.
4. `tests/` is the shipped, hash-pinned behavior suite — do NOT modify it
   (its hashes are checked). It must pass when you are done.

Start by running the test suite to see the current drift failures:

```
python -m pytest tests/ -q
```
