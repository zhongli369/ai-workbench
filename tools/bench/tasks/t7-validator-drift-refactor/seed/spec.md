# confcfg validation spec (authoritative)

A config is a JSON mapping. Two sections are known: `server` and `backup`.

Rules:

1. `port` (in `server` or `backup`): an integer in **1..65535**.
   Port `0` is **not** valid (it used to slip through on one code path —
   that was a bug, not a feature). Booleans are not integers.
2. `path` (in `server` or `backup`): a non-empty **absolute** path string.
   "Absolute" is a platform-independent string rule: the path starts with
   `/` (POSIX style, e.g. `/var/backups`) or with a drive prefix
   (e.g. `C:\data` or `D:/data`). Anything else — including `rel/dir`,
   `./x`, `~/x` — is invalid on every code path. Do not rely on
   `pathlib.PurePath.is_absolute()`, which is platform-dependent and
   disagrees with this rule on some platforms.
3. Reserved keys `__meta__` and `__comment__` are **invalid** at the top
   level of a config.
4. Validation reports the sorted list of offending field names
   (e.g. `["backup.path", "server.port"]`); an empty list means valid.
5. Type errors (config or section is not a mapping) raise an error
   instead of returning a list.

Both the load/normalize path and the report path must apply these rules
identically.
