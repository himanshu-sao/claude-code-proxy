APPROVE

Branch tip is 3b84a81. I checked everything below myself.

- Verdicts: all three round-2 reviews (api, code, security) start with a real `VERDICT: PASS` line. Each one gives concrete evidence. The api review ran a live fake-upstream matrix. The code review ran the suite plus mutation checks. The security review reran its PoCs. Round 1 had one CHANGES verdict (security), and it is closed. The round-2 security review confirms fixes for header safety (MEDIUM), `from None` chaining, CR/LF log escaping, pool-key redaction and the 8-character minimum.
- Tests: I ran the suite in a scratch copy from `git archive` at /tmp/claude-501/approve-a. `src` resolved to the copy. Result: 481 passed, 4 xfailed. The four strict xfails (`test_stream_upstream_error_is_visible_to_client[400|422|503|429]`) still XFAIL, with no XPASS.
- Scope: the diff against 67de01a touches only `src/core/errors.py`, `src/core/client.py`, `tests/test_errors.py` and `src/core/logging.py`. The `logging.py` change is the one docstring (4-line hunk, 2 lines replaced). `endpoints.py` and `response_converter.py` are untouched. No docs or env changes are needed because nothing configurable or user-facing changed.
- Round-2 security residual (unescaped ESC and U+2028 in the warning log line): accepted, not blocking. CR/LF are escaped, so records cannot be forged or split for line-based handlers. ESC and U+2028 can only affect terminal rendering. The reviewer rated it INFO.
- Round-2 code note (the cancellation test passes even when the task-cancel loop is removed): accepted, not blocking. The behaviour is correct. The reviewer showed with a probe that the handler fixes a real task leak. The build notes already admit the test is weak. It is a test-strength follow-up only.
- Interface notes for slice C are written in `round-2/review-code.md` ("Interface notes for slices C and D"). `build.md` covers the exception types but not the priming rule, so C must read the review file. The notes cover:
  - C must read `e.mapped` on `UpstreamError`. The stream path raises `UpstreamError`, which is not an HTTPException and has no `status_code`.
  - C must prime the first chunk before returning a `StreamingResponse`. The stream generator only calls upstream at the first `__anext__`.
  - `retry-after` is forwarded uncapped (1 to 10 ASCII digits). Only the endpoint's own 429 needs the 60-second cap.
  - Accounting happens once per call inside the client. C and D must not repeat it. `errors.py` must stay free of imports from config and client.

Before merging, the orchestrator should:
1. Give slice C the interface notes above. Point it at `round-2/review-code.md`, and copy them into `build.md` or the slice C prompt.
2. Merge this slice into `factory/005-error-contract`, then rerun the offline suite there. The expected result is 481 passed and 4 xfailed until D removes the xfail markers.
3. Track these non-blocking follow-ups:
   - Strengthen `test_non_stream_asyncio_cancellation_propagates_and_cleans_up`. For example, set a flag in the hanging coroutine's CancelledError handler, or check `asyncio.all_tasks()` after a tick.
   - Optionally escape ESC and U+2028 (for example with `repr()` or `unicode_escape`) in the client warning log.
   - Add a direct test for the prefix-key ordering in `redact_keys`.
   - The pre-existing `except asyncio.CancelledError: pass` in the pending loop (client.py around lines 107-110) could swallow an outer cancel. It is unchanged code and rare.
4. Expect the interim behaviour until C and D land. Non-stream errors still return `{"detail": ...}`. Stream errors give HTTP 200 with one `event: error` reading "Streaming error: UpstreamError" and no `message_stop`.
