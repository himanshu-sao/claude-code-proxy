# Build: 005-error-contract-c

Status: GREEN. Offline suite 560 passed, 0 failed, 0 xfailed, 0 XPASS. Commit hash is in the final report.

## What changed
- `src/api/endpoints.py`
  - New helpers: `_error_response`, `_mapped_response`, `_exhausted_response` (own 429, Retry-After clamped to 1..60), `_prepend`, `_empty`, `_ClientGone`, `FIRST_CHUNK_POLL_SECONDS = 0.25`, `_await_first_chunk`.
  - `create_message`: the inner try/excepts are gone and there is one outer handler, in order `UpstreamError`, `_ClientGone`, `HTTPException`, `Exception` (generic `Internal server error`, traceback logged server-side, `str(e)` never in the body). `CancelledError` is not caught.
  - Non-stream uses `get_next_client_async()`. Stream uses `get_next_client_async(stream=True)`, reads the first chunk before building `StreamingResponse`, and re-prepends it.
  - An upstream failure before the first chunk now returns a real HTTP status with the Anthropic envelope and the forwarded headers. The sync `get_next_client` is never called. Upstream `retry-after` is forwarded uncapped.
  - `validate_api_key` and FastAPI 422s keep `{"detail": ...}`.
- `tests/test_endpoints_errors.py` (new, 62 tests): all 13 spec criteria.
- Stub edits: `get_next_client_async` stubs now take `(*, stream=False)`.
  - `tests/test_endpoints.py::stub_upstream._next_async`
  - `tests/test_job003_endpoints.py::upstream._next_async`
  - `::test_top_level_max_is_forwarded_as_max_to_upstream._capture_async`
  - `::failing_upstream._next_async`
  - `tests/test_exhausted_keys.py::exhausted._none`
  - The `upstream` fixture still appends `"async"`.

## Changed expectations (old to new)
- `tests/test_job003_endpoints.py::test_non_stream_upstream_status_and_text_pass_through[400|422|503|429]`:
  `res.json()["detail"] == message` became `type == "error"`, `error.type == error_type_for_status(status)` and `error.message == message`. Reason: the old `detail` envelope is replaced by the Anthropic envelope. The status, `failures` and `rate_limits` assertions are untouched.
- `::test_stream_upstream_error_counts_as_model_failure_only_for_503_and_429[400|422|503|429]`:
  `res.status_code == 200` became `== status`. Reason: pre-first-chunk errors are real HTTP statuses now. The `failures` assertion is unchanged.
- `tests/test_exhausted_keys.py::test_exhausted_keys_return_429_with_retry_after[False|True]`:
  `res.json()["detail"].startswith("All API keys exhausted")` became `body["type"] == "error"`, `error.type == "rate_limit_error"` and `error.message.startswith("All API keys exhausted")`. The `retry-after == "7"` check is unchanged.
- `tests/test_endpoints.py::test_signal_log_failed_upstream_is_still_logged_once`: still expects 500. Added an assertion that the body equals the `api_error` envelope with `Internal server error`.
- Unchanged on purpose: the `detail` assertion in `test_top_level_effort_outside_literal_is_422_without_upstream`, and `tests/test_errors.py`.

## xfail outcome (G3 moves from D to C)
I removed only the `@pytest.mark.xfail(strict=True, reason=...)` decorator on `test_stream_upstream_error_is_visible_to_client[400|422|503|429]`. The assertion `res.status_code != 200 or message in res.text` is untouched. All four genuinely pass:
`pytest tests/test_job003_endpoints.py::test_stream_upstream_error_is_visible_to_client -v` shows 4 PASSED (not XPASS, since there is no marker).
Slice D keeps G4, G6, G12, the mid-stream tests and the byte-identical fixture.

## Commands and results
`V=~/Work/src/extra/himanshu-sao/claude-code-proxy/.venv/bin/python`, run from the worktree.
- Venv check: `import src` resolves to `.../.claude/worktrees/005-c/src`.
- Baseline before edits: `tests/ --ignore=tests/test_main.py` gave 494 passed, 4 xfailed.
- Final full suite: `OPENAI_API_KEY=test-key $V -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider -q -rxX` gave 560 passed, 0 xfailed, 0 XPASS.
- Focused: `tests/test_endpoints_errors.py tests/test_endpoints.py tests/test_job003_endpoints.py tests/test_exhausted_keys.py` gave 184 passed.
- Black and isort (line length 100) on `src` and `tests`: clean (`black --check`: 33 files unchanged, `isort --check` ok).
- Key-literal scan (`sk-`/`ghp_` followed by characters) of `src` and `tests`: no hits.
- `grep get_next_client()` in endpoints.py: only a comment.

## Acceptance criteria
All 13 pass, each covered in `tests/test_endpoints_errors.py`.
- G1: `test_status_and_body_identical_on_stream_and_non_stream` and `test_context_length_400_carries_prefix`.
- G2: the 429 with and without `retry-after` tests.
- G7 and edge 2: `test_upstream_retry_after_forwarding_rules` and `test_own_429_retry_after_is_clamped_to_1_60`.
- Edge 3: `test_x_should_retry_passes_through`.
- G8: `test_exhausted_real_config_returns_429_not_500` and `test_getter_returning_none_returns_429`. The sync getter is patched to raise.
- G9: `test_health_answers_fast_while_keys_are_exhausted`.
- G10: `test_stream_one_upstream_hit_non_stream_retries`. Stream makes 1 hit, non-stream makes 3.
- Edge 15: `test_html_502_body_is_still_valid_anthropic_json`.
- Edge 4: `test_sdk_timeout_is_a_real_http_500_before_any_body` and the real-socket test. The real-socket test returns 500 in under 4 s with `REQUEST_TIMEOUT=1`.
- Edge 5: the two `_await_first_chunk` cleanup tests.
- Edge 9: `test_one_key_429s_next_key_serves`.
- Edge 10: `test_single_key_after_429_gets_own_429_without_upstream_call`.
- Stubs and error shaping: the `get_next_client_async` call-shape test, the empty-stream test and the "boom" test.

## Mutation checks
Scratch copy `/tmp/claude-501/mut`, with `src` imported from that copy. Full offline suite per mutation:
- (a) The stream branch returns `StreamingResponse` without priming: 36 failed.
  - The failures are the 9 status-matrix tests, all stream variants of the headers, retry-after, html 502 and timeout tests, the 4 `test_stream_upstream_error_counts_as_model_failure...`, the 4 `test_stream_upstream_error_is_visible_to_client`, the G10 test and the real-socket test.
  - Reason: a 200 is returned instead of the real status.
- (b) The non-stream path renders `{"detail": ...}` again: 20 failed.
  - The failures are the 9 status-matrix tests, the non-stream variants of the envelope tests, the G10 test, the edge 10 test, and the 4 `test_non_stream_upstream_status_and_text_pass_through`.
- (c) Forwarded `retry-after` capped at 60: 4 failed, the `120` and `3600` cases on both paths.
- (d) Sync `get_next_client` on the non-stream path: 31 failed.
  - Almost every non-stream test fails, because the stubs patch the async getter only.
  - G9 initially did NOT fail. My first version slept before probing `/health`, which let the POSTs finish first. I rewrote it to launch the POSTs, assert a 50 ms sleep takes under 0.15 s, then time `/health`.
  - With the rewrite, mutation (d) fails G9 with the loop blocked for about 6 s, and the real code passes (0.3 s).

## Not verified
- Live behaviour against a real proxy and Claude Code (whether auto-compact triggers on the prompt-too-long prefix, and how Claude Code shows the error text). That is orchestrator-level live verification.
- `tests/test_main.py` is excluded, per the offline command.
- Mid-stream errors and the converter are slice D, and I did not touch them.
- The `_ClientGone` 499 body is never read by anyone, so it is only unit-tested via `_await_first_chunk` and not through HTTP.
