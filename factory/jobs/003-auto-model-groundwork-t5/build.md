STATUS: GREEN

# Build T5 - wire `emit_signal` into `create_message`

## Files changed
- `src/api/endpoints.py` (+16 lines): `from src.core import signal_log`; private helper `_emit_signal_safe(request, http_request)`; one call to it inside `create_message`'s `try`, right after T1's `logger.info(... reason=%s)` and before `convert_claude_to_openai`. The helper evaluates `http_request.headers` and `model_manager.is_auto_alias(request.model)` and calls `signal_log.emit_signal(...)` inside `try/except Exception`, logging `logger.debug("signal log skipped: %s", type(exc).__name__)`. It is inline (no executor). endpoints.py reads no env and no config field. T1's `logger.info` call is untouched and the helper adds no `reason=` line.
- `tests/test_endpoints.py` (+272 lines): autouse fixture `signal_path` and the new tests (below). No existing test was removed or edited.
- Not touched: `signal_log.py`, `config.py`, `claude.py`, any other source file.

## Tests added
- Autouse fixture `signal_path`: `delenv AUTO_SIGNAL_LOG`, patches `signal_log._log_path` to `tmp_path/auto_signal.log`, sets `_config.anthropic_api_key = None`, `reset_for_tests()` before and after.
- `test_signal_log_one_line_per_request` (alias and tier model x stream and non-stream; also checks `auto`, `stream`, `model` and that a second request appends exactly one more line)
- `test_signal_log_failed_upstream_is_still_logged_once` (stub upstream raises, 500, 1 line)
- `test_signal_log_422_is_not_logged` (invalid `reasoning_effort`, missing `messages`; spy 0 calls, no file; valid body then gives 1 call and 1 line)
- `test_signal_log_off_creates_nothing` (unset and `0` x stream and non-stream; 200, no file, `auto_signal` logger has no handlers)
- `test_signal_log_header_privacy` (real Starlette Headers via TestClient)
- `test_signal_log_failure_leaves_response_unchanged` (cases unwritable-path, emit-raises, args-raise x stream and non-stream, compared with an off baseline)
- `test_reason_line_once_with_signal_log_on`
- `test_signal_log_does_not_change_echo_or_routing` (log on/off x stream and non-stream)

## How tested (from the worktree, venv python, `OPENAI_API_KEY=test-key`)
- `python -c "import src; print(src.__file__)"` printed a path inside `.claude/worktrees/003-t5/src/__init__.py` (confirmed).
- `python -m pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py tests/test_model_manager.py tests/test_signal_log.py -q` -> **214 passed** (190 before + 24 new test cases).
- Same `tests/test_endpoints.py` run with `AUTO_SIGNAL_LOG=1` exported in the shell: 34 passed, and `logs/auto_signal.log` was still not created (autouse fixture works against a `.env`/env switch).
- `python -m black -l 100 --check src/ tests/test_endpoints.py` -> clean; `python -m isort --profile black -l 100 --check src/ tests/test_endpoints.py` -> clean.
- `ls logs/auto_signal.log` in the worktree -> No such file. `git status` shows only the two intended files (plus this build.md).
- Guard-removal check: I temporarily replaced the helper's try/except with the bare `signal_log.emit_signal(...)` call. Result: 4 failed, 30 passed (`test_signal_log_failure_leaves_response_unchanged[emit-raises-*]` and `[args-raise-*]`, stream and non-stream). I then restored the guard (file restored from a copy; `git diff --stat` back to +19 in endpoints.py) and re-ran the full suite green.

## Acceptance criteria mapping
1. one line per request, stream/non-stream, alias/tier model, 500 still logged, `auto` only for alias -> `test_signal_log_one_line_per_request`, `test_signal_log_failed_upstream_is_still_logged_once`
2. 422 not logged -> `test_signal_log_422_is_not_logged`
3. off creates nothing, no handler -> `test_signal_log_off_creates_nothing`
4. header privacy -> `test_signal_log_header_privacy`
5. failing log path -> `test_signal_log_failure_leaves_response_unchanged` (a: `unwritable-path`, b: `emit-raises`, c: `args-raise`; each stream and non-stream, compared to baseline, `reason=` count 1, `signal log skipped` count asserted)
6. T1 regression -> the three T1 tests are unchanged and pass; `test_reason_line_once_with_signal_log_on` covers the log-on count
7. echo and `stub_upstream` routing -> `test_signal_log_does_not_change_echo_or_routing`; also asserted in the failure test
8. offline suite plus black/isort -> 214 passed, both checks clean
9. no write to real `logs/`; only two files in the diff -> `logs/auto_signal.log` absent after the suite (also after a run with `AUTO_SIGNAL_LOG=1` in the env); `git status` shows only `src/api/endpoints.py` and `tests/test_endpoints.py`, plus this build.md.

## Deviations / notes
- Criterion 5 (a): `emit_signal` swallows the unwritable-path error itself, so no `signal log skipped` record appears there (the spec allows "no such record is required" in (a)). The test asserts zero such records and that the callee logged `signal_log: emit failed` at DEBUG.
- Criterion 5 (c): used the spec's wrapper approach with `sys._getframe(1).f_code.co_name == "_emit_signal_safe"`; I did not find a more robust lever. It depends on the helper's name and on `is_auto_alias` being evaluated in the helper's own frame (not in a nested lambda or comprehension).
- In the failure test the baseline is run in the same test first, then the stub call list is cleared before the failing run, so `stub_upstream == [("big", active BIG)]` is asserted for the failing run only.
- Commit trailer is `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` as the orchestrator instructed (the profile says Opus 5.5).
- Live-only items (real uvicorn headers, real `logs/` path permissions, latency under load, shutdown, real disconnects) remain UNVERIFIED, as the spec states; no port was bound.

## Commit
See the final message / `git log -1` on `factory/003-auto-model-groundwork-t5` (the hash cannot be embedded in the file it is committed with).
