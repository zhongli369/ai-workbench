<!-- canary:AIWB-26C-3f1b9d42a7e8/t8 -->

This workspace contains a `README.md` describing a three-stage log
pipeline (`pipelog`). Read it carefully — its format rules are exact.

**This is SESSION A of a two-session task.** Your scope:

1. Implement stage 1 (`parse.py`) and stage 2 (`aggregate.py`) exactly as
   specified.
2. Run them so `out/records.jsonl` and `out/stats.json` exist and are
   correct.
3. Record both stages in `PIPELINE_STATE.json` per the README checkpoint
   contract.

Do NOT start stage 3 (`render.py` / `report.md`). A second session will
resume from your checkpoint and finish the pipeline. Stop when stages
1–2 are done and recorded.
