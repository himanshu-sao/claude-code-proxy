VERDICT: CHANGES

Scope: `git diff 67de01a factory/005-error-contract` (tip 1cff272), read from a `git archive` copy in /tmp/claude-501/whole-review/copy. The main checkout was not touched.

The design is delivered end to end. One small blocker remains: two new tests fail on Python 3.9, which is the repo minimum. Nothing in `src/` is wrong on 3.9.

## Test results
- Shared venv (Python 3.14), `tests/ --ignore=tests/test_main.py`: **571 passed, 0 xfailed**. `src` resolved to the copy. `black --check src` and `isort --check src` are clean.
- System Python 3.9.6: **569 passed, 2 errors on one run, 1 failed plus 61 passed on the file alone.** The baseline 67de01a on 3.9 gives 377 passed, 4 xfailed, so this is a regression from slice C's tests.
  - `tests/test_endpoints_errors.py::test_disconnect_while_waiting_cancels_upstream_and_cleans_up` errors at fixture setup.
  - `tests/test_endpoints_errors.py::test_handler_cancellation_cleans_up_and_is_not_a_model_failure` errors or fails, depending on run order.
  - Cause: the sync `hanging` fixture (line 431) builds `asyncio.Event()` outside a running loop. On 3.9 `Event()` binds to `get_event_loop()` at construction. That raises "There is no current event loop", or binds to a different loop than pytest-asyncio's ("got Future attached to a different loop").
  - Python 3.10+ binds lazily, so 3.14 hides it.
  - Fix: create the Event inside the async test, or make the fixture `async def`, or build `state["started"]` lazily.
  - `src/core/client.py:87,155` creates its Events inside running coroutines, so production code is fine.

## Findings, ranked

### 1. CHANGES (blocking, small): 3.9 test failure (above)
The repo minimum is 3.9 (`pyproject.toml:24`), and the offline command must be green on it.

### 2. Dead code left behind (LOW, fix in this job)
- `src/conversion/response_converter.py:83` `convert_openai_streaming_to_claude` is still there. Nothing imports it. Audit item P22 listed it for removal, and it now carries the old error behaviour.
- Unused imports:
  - `Any` in `src/core/errors.py:8` is new.
  - `ChatCompletionChunk` in `client.py:9` and `OpenAIClient` in `endpoints.py:18` also exist in 67de01a.
  - `black` and `isort` do not flag them.
- `MappedError.retryable` is computed (`errors.py`) but never read. `MappedError.counts_as_model_failure` is also never read. The client calls the module function `counts_as_model_failure(status, str(exc))` directly. The result is the same, but the brief's single "tuple" is only half used. This is speculative surface, not a bug.
- Stale references: no live reference to `classify_openai_error` remains in `src/`, README, QUICKSTART or `scripts/`. It appears only in `tests/test_errors.py:211` as an absence assertion. `logging.py` docstring was updated.

### 3. Docs (LOW)
- Required docs are present. `STREAM_MAX_RETRIES` is in `.env.example:93` and in README Environment Variables (README:134). The default is 0 and the text is accurate.
- QUICKSTART has a new "Errors" section. It correctly states that 401 (proxy key) and 422 keep `{"detail": ...}`. It says that Claude Code's mid-stream display is unchecked, which is honest.
- README's feature list (README:20,443) does not mention the Anthropic-shaped errors, the real status codes or the mid-stream `event: error`. The profile says to update README "features" on behaviour changes. This is a one-line gap.
- No doc or script still describes the old `{"detail": ...}` upstream-error shape.
- `scripts/test_desktop_compat.py:162` and `compat.py:217` use `{"detail":"Not Found"}` for non-`/v1` 404s. That is the unchanged compat behaviour.
- `tests/test_main.py` and `scripts/test_cancellation.py` do not depend on error bodies.

### 4. The approved design, checked against the code (all delivered)
- **Anthropic envelope and real status.**
  - Non-stream: `UpstreamHTTPError` is rendered by the `create_message` handler (endpoints.py ~L270-280) via `_mapped_response`.
  - Stream: `_await_first_chunk` raises `UpstreamError` before the `StreamingResponse` exists, and the same handler renders it.
  - Types come from the `_TYPE_BY_STATUS` table plus 4xx/5xx fallbacks in `errors.py`.
- **Headers.**
  - Forwarded: `retry-after` (digits only, 1 to 10 chars, uncapped), `x-should-retry`, `request-id`, `x-request-id`, `anthropic-ratelimit-unified-*`. Values are printable ASCII only and at most 256 chars (header-injection safe).
  - Own 429 (`_exhausted_response`): `max(1, min(60, int(...)))` as `Retry-After`.
  - Not covered: an HTTP-date `retry-after` from upstream is dropped, not forwarded. That is consistent with "integer seconds".
- **Pre-first-byte.** The stream path calls `get_next_client_async(stream=True)`, then `_await_first_chunk` for every stream. A disconnect during the wait cancels the upstream call and returns 499.
- **Mid-stream.**
  - Probe: a TestClient run through the real `create_message`. The upstream raised a 503 after yielding one chunk, with a message containing `"` and `\n`.
  - Result: HTTP 200, `message_start`, `content_block_start`, `ping`, one text delta, then `event: error` with valid JSON (`{"type":"error","error":{"type":"api_error","message":"boom \"q\"\n x"}}`). There was no `message_stop`, no `content_block_stop` and no `message_delta`.
  - Accounting was one warning line, `model_error=True`.
- **One shared mapping module.** `src/core/errors.py` is used by `client._handle_upstream_exception` for both stream and non-stream. That function calls `map_upstream_error`, then `_report_model_error`, which calls `counts_as_model_failure`. The HTTP path renders the same `MappedError`. `errors.py` imports nothing from config or client. `report_rate_limit` is called once per client call.
- **`STREAM_MAX_RETRIES`.** Parsed by `Config._parse_stream_max_retries` (default 0, bad or negative gives 0 with a warning). Passed only when `stream=True`.
- **The prompt-too-long token.** `capability_rejected: prompt_too_long ` is prepended for 400/413 when the context-length triggers match, and the upstream text is kept after it. errors.md L2460 confirms Claude Code treats the token like "Prompt is too long".
- **The four xfails.** They are removed, and the suite shows 0 xfailed.

### 5. Mid-stream path end to end (correct)
Flow: `create_message` (endpoints.py ~L225-250) calls `_await_first_chunk`, then `_prepend(first, gen)`, then `convert_openai_streaming_to_claude_with_cancellation`.
- First-chunk failure:
  - `_await_first_chunk`'s `except BaseException` closes `gen`, pops `active_requests` and re-raises.
  - The client's own `finally` has already deleted the entry.
  - The outer handler returns the real HTTP error.
- Mid-stream failure:
  - The exception raised inside `_prepend`'s `async for` ends `_prepend`, whose `finally` calls `gen.aclose()` on a generator that has already finished.
  - The client's `finally` has already removed `active_requests[request_id]`.
  - The converter catches `UpstreamError` before `HTTPException` (needed because `UpstreamHTTPError` is both), yields one error event and returns. Nothing leaks.
- Empty upstream: `StopAsyncIteration` goes to `_empty()`, and the converter emits a normal empty message. This is the old behaviour, and it is acceptable.
- Client disconnect after the first chunk: the converter `break`s and does not explicitly `aclose` the `_prepend` generator. The generator is finalised by GC or the asyncgen hook, which is the same as the old code. `active_requests` is cleared only when that finaliser runs. This is pre-existing, and I rate it informational.

### 6. Regressions
- Success paths are unchanged. The converter's success body is untouched, and existing tests pass.
- `/v1/messages/count_tokens` is unchanged. It still returns `str(e)` on its 500.
- `/test-connection` now gets `UpstreamHTTPError` from `create_chat_completion`. Its `except Exception` renders `str(e)`, which is now the redacted upstream text (no `Unexpected error:` wrapping). That is acceptable.
- `/health` and `/v1/models` are untouched.

## Follow-ups: confirmed, with a ranking
1. **Lone surrogate in upstream text (MEDIUM).** I reproduced it with a stub that raised a 400 with `bad \ud800 text`. Two things break. The client's `_log.warning` hits a `UnicodeEncodeError` in the log handler, which only prints to stderr. Then `JSONResponse` rendering in `_error_response` (endpoints.py) raises `UnicodeEncodeError`, so the response is a **500 with a non-JSON "Internal Server Error" body** instead of the mapped 400. The same text mid-stream would abort `error_json`/the encode and end the stream. This is rare (upstream must emit lone surrogates) but it loses the real status. Suggested fix: `errors="replace"`-sanitise the message in `map_upstream_error`. This is the best candidate to fix in this job, but it is not blocking.
2. **No total first-chunk deadline (MEDIUM-LOW).** A trickling upstream (keep-alives only) can hold a worker until the client disconnects. Non-stream has the same bound. Confirmed.
3. **`/test-connection` and `count_tokens` use `str(e)` (LOW, pre-existing).** `count_tokens` is unchanged. `/test-connection` now carries redacted text only. Confirmed.
4. **Weak disconnect tests (LOW).** Confirmed (slice C LOW 1 to 3). Add an assertion that the first chunk is emitted once.
5. **Catch-all traceback logs a chained cause (LOW).** `traceback.format_exc()` is logged in `endpoints.py` and the converter. Confirmed. The `from None` in the client removes the chain for upstream errors only.
6. **`Unexpected error: <SDK text>` for RST/EOF mid-stream (LOW).** Confirmed, wording only. Non-APIError exceptions are not redacted by the "unexpected" path beyond key redaction.
7. **ESC and U+2028 not escaped in the client warning log (INFO).** Confirmed. CR and LF are escaped.

New items I add: the dead `convert_openai_streaming_to_claude` and unused `Any`, the README features line, the unused `retryable` field, and the Python 3.9 test fixture (blocking).

## Worktrees (not removed)
All 19 listed branches in `git worktree list` are ancestors of `factory/005-error-contract`. The `005-*` branches are not yet in `feat/virtual-auto-model` (67de01a).
- **Safe to remove after the merge (clean, merged):**
  - `.claude/worktrees/005-a`
  - `.claude/worktrees/005-b`
  - `.claude/worktrees/005-c`
  - `.claude/worktrees/005-int`, once `factory/005-error-contract` is merged into `feat/virtual-auto-model`
  - `.claude/worktrees/003-t1` to `003-t5`
  - `.claude/worktrees/fix-exhausted-keys`
  - `.claude/worktrees/fix-max-retries`
  - `.claude/worktrees/integrate-fixes`
  - `.claude/worktrees/test-gaps`
  - `.claude/worktrees/friendly-villani-59a0bb` (detached HEAD b3997aa, an ancestor of 67de01a, clean)
- **Not safe yet:**
  - `.claude/worktrees/003-t6` has an untracked `factory/jobs/003-auto-model-groundwork-t6/round-1/review-security.md` that does not exist in the main checkout. Copy or commit it first.
  - `.claude/worktrees/005-d` has an untracked `factory/jobs/005-error-contract-d/` folder. The main checkout holds a superset (it also has `decision.md`, `refined-prompt.md`, `round-1`), so it is probably duplicated. Still, run `diff -r` before removing it.
- The main checkout has `M factory/board.json` and the untracked `factory/jobs/005-error-contract*` folders, which must not be lost.
