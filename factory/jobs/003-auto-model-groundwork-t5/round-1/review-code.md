VERDICT: PASS

Reviewed build b949596 against spec 87143c9. No correctness bugs found. Three non-blocking notes (N1-N3) are at the end.

Verification I ran (worktree, venv python, `OPENAI_API_KEY=test-key`, `src.__file__` confirmed inside the worktree):
- The offline suite (effort_mapper, endpoints, context_manager, model_manager, signal_log): 214 passed.
- `tests/test_endpoints.py` with `AUTO_SIGNAL_LOG=1` exported: 34 passed. `logs/` contains only `proxy.log`, and `git status` is clean.
- black -l 100 --check on src/ and tests/test_endpoints.py: clean. isort --profile black -l 100 --check: clean.
- `git diff 1765c8e HEAD -- tests/test_endpoints.py` has 0 removed lines, so it is additions only. The 190 existing tests pass unmodified.

Findings by area:

1. Call site (src/api/endpoints.py:120-122, helper at 54-65)
   - `_emit_signal_safe(request, http_request)` is called exactly once, inside the `try`. It comes after T1's `logger.info(... reason=%s)` (108-118) and before `convert_claude_to_openai`, the disconnect check and the `if request.stream:` split.
   - T1's `logger.info` is untouched: the diff only adds lines, and the helper logs at DEBUG with no `reason=` text.
   - The helper imports `signal_log` as a module and calls `signal_log.emit_signal`, so patching works.
   - Mutation checks in a scratch copy:
     - Removing the call: 16 failures.
     - Calling only on non-stream requests: 6 stream failures.
     - Calling twice: 12 failures.
     - Hard-coding `is_auto_alias` to False: 4 failures (the auto=True cases plus args-raise).
   - So one-line-per-request, stream and auto are all genuinely pinned.

2. Guard (criterion 5c, tests/test_endpoints.py `_setup_failure`, "args-raise")
   - Guard removal: I copied src/ and tests/ to `$TMPDIR/scratch5` and replaced the try/except with the bare `signal_log.emit_signal(...)` call. Exactly the four guard-dependent tests fail: `emit-raises-{stream,non-stream}` and `args-raise-{stream,non-stream}`. This matches build.md. The scratch dir was not under the real worktree, and no real file was edited.
   - Brittleness: the `sys._getframe(1).f_code.co_name == "_emit_signal_safe"` wrapper depends on the helper's name and on `is_auto_alias` being evaluated in the helper's own frame. A nested lambda or comprehension would break it, and `sys._getframe` is CPython-only.
   - It is not silently vacuous. If the helper were renamed or the argument evaluation moved, the wrapper would never raise. The test would then fail loudly: `spy == []` fails because the stub `emit_signal` is called, and `skipped == ["signal log skipped: RuntimeError"]` fails. So the failure mode is a loud red test, not a false green.
   - A sturdier, rename-proof variant exists: compare code objects, `sys._getframe(1).f_code is endpoints._emit_signal_safe.__code__`. A rename then raises AttributeError at test time, which is just as loud, and the check needs no string literal. It is optional. I do not recommend alternatives such as counting calls, because they are more brittle.
   - The test is also a fair way to cover "arguments evaluated before `emit_signal` is entered": `http_request.headers` cannot be made to fail through TestClient.

3. Autouse fixture `signal_path` (tests/test_endpoints.py:71-84)
   - There is no state leak. It uses only `monkeypatch`, which auto-reverts `delenv`, `_log_path` and `_config.anthropic_api_key`. `reset_for_tests()` runs before and after, so the global `auto_signal` logger's handler cannot survive into the next test. The new test `test_signal_log_off_creates_nothing` also asserts `handlers == []`.
   - It makes real-`logs/` writes impossible for this module even when `.env` sets `AUTO_SIGNAL_LOG=1`: the env is deleted and `_log_path` is redirected to tmp_path, so even a test that turned the switch on writes into tmp. I confirmed this with `AUTO_SIGNAL_LOG=1` exported.
   - Its scope is this module only. Other offline test modules (test_compat_endpoints, test_signal_log) do not POST to `/v1/messages`, and `test_main` is live-only. This is acceptable for now.
   - It does not change existing behaviour: all 190 existing tests pass. Setting `anthropic_api_key` to None only removes the 401 risk.

4. Test quality
   - The new cases total 24: 4 + 1 + 2 + 4 + 1 + 6 + 2 + 4. They are distinct (alias vs tier × stream, 422 variants, off values × stream, failure case × stream, log on/off × stream).
   - The 422 test proves `emit_spy == []` and that the file does not exist, then runs a valid body on the same fixture and sees 1 spy call and 1 line.
   - Header privacy uses the real Starlette Headers via TestClient. It checks names, the `beta`/`sid` flags and the exact `sid_hash`. It also checks that no sentinel value appears in the raw file, including the bare `SENTINEL-` prefix and `Bearer`. The sentinel checks are real.
   - Failure tests compare against a baseline from the same test (status plus body without id, or the ordered SSE event types). They also assert the T1 `reason=` count is 1, that routing was recorded, and the exact `signal log skipped: RuntimeError` record. For the unwritable path they assert no skipped record and that the callee's own `signal_log: emit failed` DEBUG line appears.
   - Some tests would not fail if the feature were removed: `test_signal_log_off_creates_nothing`, `test_reason_line_once_with_signal_log_on` and the log-off halves of the echo test. They are intentional negative or regression guards, and the positive tests cover removal (see the mutation results in item 1).

5. Inline, not an executor
   - The decision is sound and well documented in the spec (a no-op unless enabled, deterministic line order, nothing pending at shutdown). The helper docstring and the comment at endpoints.py:120-121 are accurate.
   - One nuance is in N2.

6. Python 3.9, formatting and scope
   - Python 3.9 is safe: no `X | Y`, no `match`. `sys._getframe` is fine.
   - The diff touches only src/api/endpoints.py, tests/test_endpoints.py and the job folder. signal_log.py, config.py and claude.py are untouched.
   - The `—` in the `# noqa` comment matches the existing line 50 style.

7. build.md
   - The first line is `STATUS: GREEN`. The criteria mapping and the numbers (214 passed, 4 failures with the guard removed) match what I reproduced.
   - The "Files changed" section says endpoints.py is "+16 lines", but the actual diff is +19. See N3.

8. Docs
   - No docs are required. `AUTO_SIGNAL_LOG` was introduced in T3 and belongs to the docs sub-job. T5 adds no env var or config and no user-facing behaviour while the switch is off.

Non-blocking notes:
- N1: The code-object comparison in item 2 is an optional hardening of the 5(c) test.
- N2: The helper docstring says "No-op unless AUTO_SIGNAL_LOG is on". The argument `model_manager.is_auto_alias(...)` is evaluated even when the switch is off. That is a trivial, cheap call, but the docstring is slightly imprecise.
- N3: The build.md "+16 lines" wording is stale (actual +19).

Live-only items stay UNVERIFIED, as the spec states: real uvicorn headers, the real `logs/` path and its permissions, latency under load, shutdown, and real disconnects.
