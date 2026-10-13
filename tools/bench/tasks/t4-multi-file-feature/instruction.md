<!-- canary:AIWB-26B-7f3d9e2b15c8/t4 -->
This workspace holds a tiny inventory CLI (`model.py`, `cli.py`, `README.md`).

Acceptance criteria (all required):
1. The `list` command gains a `--json` flag. With the flag, stdout is a JSON
   array of objects with exactly the keys "name", "qty", "price" — nothing
   else on stdout.
2. Without the flag, the existing tab-separated text output is unchanged.
3. The `add` command keeps working unchanged.
4. `README.md` documents the new flag in its usage section.

Verify your work by actually running the CLI before you finish.
