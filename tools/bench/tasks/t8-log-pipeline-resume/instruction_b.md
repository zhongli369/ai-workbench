<!-- canary:AIWB-26C-3f1b9d42a7e8/t8 -->

This workspace contains a `README.md` describing a three-stage log
pipeline (`pipelog`). **You are SESSION B resuming an interrupted task.**
A previous session may have completed some stages.

1. Read `README.md` and `PIPELINE_STATE.json` (if present). Trust the
   checkpoint: stages whose recorded `sha256` still matches their output
   file are DONE — do not redo them, do not regenerate their outputs.
2. If a stage is missing from the checkpoint or its hash does not match,
   that stage (and only that stage) must be (re)done.
3. Complete the remaining stage(s) so the whole pipeline is finished:
   `report.md` rendered exactly per the README, and every stage recorded
   in `PIPELINE_STATE.json`.

Work only on what the checkpoint says is incomplete.
