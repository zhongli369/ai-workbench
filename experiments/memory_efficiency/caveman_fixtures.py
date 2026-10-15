"""D3b - Sample model-output fixtures for the caveman A/B evidence eval.

Each fixture is representative SAMPLE model output that THIS prototype
invents (not copied from caveman's repo): verbose assistant prose with real
payload (commands, paths, error codes, numbers) that a voice rule must never
alter, plus control fixtures (already-terse, payload-heavy) to test the
honesty boundaries. `original` is what a model would write in normal mode;
the transform approximates the caveman voice on the PROSE ONLY.
"""

FIXTURES: list[dict[str, str]] = [
    {
        "name": "chatty_help",
        "original": (
            "Sure! I'd be happy to help with your deployment issue. Just note "
            "that the root cause here is that the auth token expiry check uses "
            "the wrong comparison operator. Please note that the middleware "
            "currently compares against `<` instead of `<=`, which means a "
            "token that expires exactly at the boundary is treated as valid. "
            "Actually, as you can see, the fix is pretty simple: run `npm run "
            "test` in the project root at C:\\Users\\dev\\auth-service and "
            "verify the new count shows 128 passing and 0 failing. If you hit "
            "ENOTFOUND or the error `Error 1045`, double check the .env file. "
            "Hope this helps! Let me know if you have any questions."
        ),
    },
    {
        "name": "technical_brief",
        "original": (
            "The regression comes from the retry loop in worker.py. In order "
            "to reproduce, run `python -m pytest tests/test_worker.py -k retry` "
            "with the fixture file at fixtures/worker_crash.json. Actually, the "
            "important thing to note is that the loop retries for 5 seconds "
            "but the backoff uses 2x the previous delay, capping at 30 seconds, "
            "which masks the 401 for 2.5x longer than necessary. It is worth "
            "noting that reverting commit 4f2c1a9 plus removing line 47 restores "
            "the previous behaviour. Let's get started on that."
        ),
    },
    {
        "name": "already_terse",
        "original": (
            "Bug in auth middleware. Token expiry check uses `<` not `<=`. "
            "Fix: change operator. Tests: 128 passed."
        ),
    },
    {
        "name": "payload_heavy",
        "original": (
            "Run `git checkout main` then edit src/config.py: set PORT=8080, "
            "DB_DSN=postgres://db:5432/app, RETRY=3. Deploy the built binary "
            "at dist/app.exe. If the health check returns HTTP 503, the "
            "vhost /etc/apache2/sites-available/site.conf points at the wrong "
            "docroot. The rollout plan in docs/rollout.md covers steps 1-5."
        ),
    },
    {
        "name": "mixed_zh_prose_retained",
        "original": (
            "当然可以！我很乐意帮忙排查这个故障。实际上，希望你先运行 "
            "`python -m brain.cli telemetry` 看看调用计数，然后检查 "
            "C:\\Users\\dev\\logs\\run.log 里的 `Error 1045`。As for the next "
            "step, run `git push origin main` after the tests pass. "
            "Hope this helps!"
        ),
    },
]