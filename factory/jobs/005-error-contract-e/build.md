GREEN. Branch `factory/005-error-contract-e`, worktree `.claude/worktrees/005-e`. Commits on top of 1cff272: 0380c1a (py3.9 fixture), a7fdf2d (truncated stream + surrogate + empty text + cleanup), 655f78a (README). Not merged, not pushed.

## What changed
- tests/test_endpoints_errors.py: `hanging` fixture is now `async def`, so its `asyncio.Event()` objects are built inside the running loop (fix 1). No assertion touched.
- src/core/errors.py: `truncated_stream_error()` (MappedError: 502, `api_error`, "Upstream stream ended before a finish_reason was received", retryable True, counts_as_model_failure False) and constant `TRUNCATED_STREAM_MESSAGE`. `map_upstream_error` replaces lone surrogates (U+D800-DFFF) with U+FFFD once, after redaction, for both APIError and non-APIError paths (fix 3). A non-APIError with empty or whitespace `str(exc)` gives `Unexpected error: <TypeName>` (fix 4). Unused `Any` import removed (fix 5).
- src/core/client.py: `create_chat_completion_stream` tracks whether any chunk had a truthy `finish_reason` in any `choices[*]`; a usage-only chunk (empty choices) does not count. If the iterator ends with none seen it raises `UpstreamError(self._handle_truncated_stream())` and does NOT yield `[DONE]` or call `report_model_success()`. `_handle_truncated_stream` does the one `_report_model_error` call (a log line only, since the error is not a model failure), and the existing `except UpstreamError: raise` passes it through, so it is reported exactly once.
- tests/test_errors.py: mapper tests for surrogates and empty text. New tests/test_truncated_stream.py (client layer, endpoint layer, surrogate through the endpoint).
- README.md: one feature bullet (real HTTP status in the Anthropic shape; a stream failing after it began, including one ending without a finish_reason, ends with one `event: error` and no `message_stop`). No claim about Claude Code behaviour. QUICKSTART not edited: it does not contradict fix 2.
- Only allowed files edited. The converter, endpoints.py and config.py are untouched.

## Behaviour implemented / decisions
- Mid-stream truncation (text, then clean close): the converter's existing UpstreamError handler emits one `event: error` (502 api_error, fixed message) and nothing after it. HTTP status stays 200 because headers were sent.
- Zero chunks then close: `_await_first_chunk` calls `gen.__anext__()`. The generator now raises UpstreamError (not StopAsyncIteration) before yielding anything, so the endpoint returns a real HTTP 502 with the Anthropic envelope and no message_start. Before this change the StopAsyncIteration branch (`_empty()`) returned a 200 with an empty message. That branch is now unreachable through the real client; it still serves stub clients, and the existing `test_empty_stream_still_returns_a_response` still passes unchanged.
- Normal finishes (`stop`, `tool_calls`, `length`, with and without a trailing usage chunk): unchanged. `[DONE]` is last and success is reported once.
- The SDK strips a real `data: [DONE]` line. So an upstream that sends `[DONE]` but never a finish_reason cannot be told apart from a clean close at this layer, and both are treated as truncated errors. This is the user's accepted risk. A provider that omits finish_reason will show errors on good replies. I could NOT verify any real provider (including the NVIDIA models) against this; no live calls were made.
- A finish_reason on a non-first choice also counts as a finish (the converter reads only choices[0], but the spec said "any choices[*]").

## Failing before, passing after
Scratch copy of the unmodified 1cff272 under /tmp/claude-501/red, with only the new/updated test files copied in. For the venv run, TRUNCATED_STREAM_MESSAGE was inlined, because the import does not exist on old code (the first attempt is a collection ImportError).
- venv py3.14: 11 failed, 114 passed on tests/test_truncated_stream.py + tests/test_errors.py:
  - the 4 `test_stream_without_finish_reason_raises_502_and_no_done[...]` cases
  - test_text_then_clean_close_is_one_error_event_and_nothing_after
  - test_zero_chunks_is_a_real_http_502_envelope
  - test_non_stream_400_with_lone_surrogate_is_a_valid_envelope
  - test_midstream_lone_surrogate_yields_one_valid_error_event
  - test_mapper_message_is_always_utf8_encodable
  - test_empty_text_for_non_http_errors_uses_the_type_name[exc0] and [exc1]
- /usr/bin/python3 (3.9.6) on old src with the old test_endpoints_errors.py: the `hanging` tests error. In the scratch run, `test_handler_cancellation_cleans_up_and_is_not_a_model_failure` failed (1 failed, 61 passed on that file). The full-suite 3.9 run on old code plus new tests: 11 failed, 579 passed, 2 errors (the two `hanging` tests).
- Fix-5 items (unused import, README) have no test.
After the fix, all of these pass.

## Mutation checks (scratch copies of the final tree)
- mut1, truncated-stream raise replaced by `pass`: 6 failed (4 client-level cases, text-then-close, zero-chunks 502).
- mut2, surrogate sanitising removed: 3 failed (non-stream 400, mid-stream, mapper test).
- mut3, empty-text fallback removed: 2 failed.

## Final gate (from the worktree; `src` confirmed to resolve to .claude/worktrees/005-e/src on both interpreters)
- `OPENAI_API_KEY=test-key ~/Work/src/extra/himanshu-sao/claude-code-proxy/.venv/bin/python -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider -q` -> 592 passed (3.14; baseline 571), 0 xfailed, 0 XPASS.
- `OPENAI_API_KEY=test-key /usr/bin/python3 -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider -q` -> 592 passed (3.9.6; baseline 569 passed + 2 errors), 0 errors.
- tests/test_midstream_errors.py (includes the byte-identical success test, untouched): 11 passed.
- black -l 100 --check and isort --profile black -l 100 --check on src/ and tests/: clean.
- No key-like literals added. The grep hits are the existing README placeholders at lines 188 and 230.

## Not verified
- Behaviour against any real provider's stream, including whether they send finish_reason on every reply (see above).
- How Claude Code displays the mid-stream `event: error` or the 502.
- tests/test_main.py is excluded per the suite command; the live-integration tests were not run.
- This build.md was written into the main checkout's untracked factory/jobs folder, where rework.md lives. The worktree has no factory/jobs files.
