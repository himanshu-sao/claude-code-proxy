APPROVE

- Re-ran the offline suite in a fresh scratch copy of `factory/005-error-contract-c` (`src` resolves to the copy): 560 passed, 0 failed, 0 xfailed, 0 XPASS. Matches build.md.
- All three round-1 reviews carry `VERDICT: PASS` with evidence. I spot-checked the endpoints diff and it matches the spec: non-stream uses `get_next_client_async()`, stream uses `get_next_client_async(stream=True)` and primes the first chunk before `StreamingResponse`, `_prepend`/`_empty` feed the converter, own 429 is clamped 1..60, upstream `retry-after` is forwarded uncapped, and the outer handler has no `str(e)` in the 500 body.
- Diff touches only the spec'd files: `src/api/endpoints.py`, new `tests/test_endpoints_errors.py`, the stub and expectation edits in `tests/test_endpoints.py`, `tests/test_job003_endpoints.py`, `tests/test_exhausted_keys.py`, and `factory/jobs/005-error-contract-c/build.md`.
- Changed expectations are legitimate. Each old `detail` assertion became an envelope assertion with the same message. Each `status_code == 200` became `== status`, and the `failures`/`rate_limits` checks are untouched. The four strict xfail decorators were removed while the assertion `res.status_code != 200 or message in res.text` stays as written. That is the approved G3 handling, not a weakening, because the assertion still holds and the decorator was the only thing that would turn green into red.
- Blocking issues: none.

Non-blocking gaps (track as follow-ups, do not block):
- LOW 1: the two disconnect tests (`test_endpoints_errors.py` ~454-471) would still pass if `client.cancel_request` or the explicit `active_requests.pop` were removed. Strengthen by asserting the cancel call and that `active_requests` is empty after the disconnect.
- LOW 2: nothing asserts the first chunk is emitted exactly once. A double-prepend would pass `"hi" in res.text`. Add a direct `_prepend` unit test or count content deltas.
- LOW 3: no HTTP-level test for the `_ClientGone` 499 envelope. The body is never read by a client, so this is low risk.
- Security: the hang bound on the pre-first-chunk wait relies on the SDK per-phase `REQUEST_TIMEOUT`. An upstream that trickles keep-alives can hold a worker until the client disconnects. Non-stream has the same bound. Follow-up: consider a total deadline.
- Security (pre-existing, out of scope): `str(e)` leaks exception text in `count_tokens` (`endpoints.py` ~325) and `/test-connection`. Follow-up.

Notes slice D must satisfy (confirmed written in review-code.md "What slice D must know" and build.md):
- The converter receives `_prepend(first, gen)` or `_empty()`, never the raw generator. `_prepend` closes `gen` in its `finally`.
- An `UpstreamError` after the first chunk surfaces inside the converter's `async for`. D must catch it there, read `e.mapped`, and emit an Anthropic `event: error` SSE with the mapped type and message (today it emits the generic "Streaming error: UpstreamError"). D must not emit `message_stop` after it.
- The outer handler in `create_message` no longer covers the stream body. Stream-body errors are D's responsibility.
- Accounting is done once inside `OpenAIClient`. D must not call `report_model_failure` or `report_rate_limit`.
- G3 (the four pre-first-chunk stream tests) is already satisfied here. D keeps G4, G6, G12, the mid-stream tests and the byte-identical fixture.

Before merging (orchestrator):
- Merge `factory/005-error-contract-c` as specified. Record the 4 xfail removals in the merge notes.
- Live Claude Code verification (whether it shows the `event: error` message text, and the 429/503 retry behaviour) is still unverified from brief 3.5. It belongs to the end-of-job live run, not to this slice. Do not claim it as done.
