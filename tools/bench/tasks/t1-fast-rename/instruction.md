<!-- canary:AIWB-26B-7f3d9e2b15c8/t1 -->
In this workspace, rename the function `total_price` to `compute_total`
everywhere it appears (definition in `calc.py` and all call sites in
`main.py`). Behavior must stay identical. Do not change the `discount`
function. When done, `python main.py` must still print the same two lines.
