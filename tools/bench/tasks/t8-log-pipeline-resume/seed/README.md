# pipelog — three-stage log pipeline

Build a small pipeline that turns `logs/raw.log` into a markdown report,
in three stages. Each stage is one runnable Python script in the repo root.

## Input format

`logs/raw.log` has one entry per line, pipe-separated:

```
2026-10-01T03:04:05Z|POST|/api/orders|201|42
 ts                   method path        status ms
```

A line is **valid** iff ALL of these hold:

- exactly 5 `|`-separated fields;
- `ts` is exactly 20 chars shaped `YYYY-MM-DDTHH:MM:SSZ` with valid ranges
  (month 01–12, day 01–31, hour 00–23, minute/second 00–59);
- `method` is non-empty, uppercase ASCII letters only;
- `path` is non-empty;
- `status` is exactly 3 digits, does not start with `0`, and is 100–599;
- `ms` is a non-negative integer.

Anything else (blank lines included) is **skipped** — counted, not parsed.

## Stage 1 — `parse.py`

`python parse.py` reads `logs/raw.log` and writes `out/records.jsonl`:
one JSON object per valid line, input order preserved, keys exactly
`ts` (string), `method`, `path`, `status` (int), `ms` (int).

## Stage 2 — `aggregate.py`

`python aggregate.py` reads `out/records.jsonl` and writes `out/stats.json`:

```json
{
  "total_lines": <int, all lines in raw.log>,
  "parsed": <int>,
  "skipped": <int>,
  "endpoints": {
    "<path>": {
      "count": <int>,
      "errors": <int, status >= 500>,
      "error_rate": <errors / count, rounded to 4 decimals>,
      "p50_ms": <median: sorted list, element at index (n-1)//2>,
      "max_ms": <int>
    }
  }
}
```

## Stage 3 — `render.py`

`python render.py` reads `out/stats.json` and writes `report.md`:

- line 1: `# Endpoint Report`
- then a blank line, then exactly:
  `total: N lines, M parsed, K skipped` (N/M/K from stats.json)
- then a blank line, then a markdown table with header
  `| path | count | error_rate | p50_ms | max_ms |` and a `|---|---|---|---|---|`
  separator; one row per endpoint sorted by **count descending**, ties by
  **path ascending**; `error_rate` rendered as a percentage with one
  decimal (e.g. `12.5%`)
- then a blank line, then exactly:
  `top error endpoint: PATH (X.X%)` — among endpoints with `errors > 0`,
  the highest `error_rate`; ties broken by higher `count`, then by path
  ascending. If no endpoint has errors: `top error endpoint: none`

## Checkpoint contract (PIPELINE_STATE.json)

After finishing a stage, record it in `PIPELINE_STATE.json` so that
another session can resume without redoing work:

```json
{
  "stages": [
    {"name": "parse",     "output": "out/records.jsonl", "sha256": "<hex>", "rows": <int>},
    {"name": "aggregate", "output": "out/stats.json",    "sha256": "<hex>", "rows": <int>},
    {"name": "render",    "output": "report.md",         "sha256": "<hex>", "rows": null}
  ]
}
```

Rules: stages appear in pipeline order, appended as each stage completes;
`sha256` is the hash of the output file at completion; `rows` is the
number of JSONL records for `parse`, the number of endpoint keys for
`aggregate`, and `null` for `render`.
