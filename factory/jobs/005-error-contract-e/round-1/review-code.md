VERDICT: PASS

Tests: scratch copy of the branch tip (`src` resolved to /tmp/claude-501/code-e/src on both interpreters). Venv 3.14 gave 592 passed. System Python 3.9 gave 592 passed, 0 errors. `black -l 100` and `isort` are clean. No xfails.

Findings:

1. (info, correct) Truncation logic, src/core/client.py:169-190.
   - `any(c.get("finish_reason") for c in choices or [])` handles every case you listed:
     - A usage-only chunk (empty `choices`) is not a finish.
     - `None` and `""` are falsy, so they are not a finish.
     - A finish_reason on the same chunk as content counts.
     - `stop`, `tool_calls`, `length` and `content_filter` are all truthy, so they count.
     - A finish_reason on any choice of a multi-choice chunk counts.
   - Truncation raises `UpstreamError` before `[DONE]` is yielded and before `report_model_success()`.
   - `_handle_truncated_stream` calls `_report_model_error` once. That call only logs, because 502 with this text is not a model failure. The existing `except UpstreamError: raise` passes the error through, so the reporting happens once.
   - The client-cancel branch still returns early at line ~176 and never reaches the truncation check, so a cancel is not reported as truncation.
   - Normal finishes report `[DONE]` last and success once. The tests pin this for stop, tool_calls and length, each with and without a trailing usage chunk.

2. (info, correct) Zero chunks then close. `_await_first_chunk` (src/api/endpoints.py:148-184) awaits `gen.__anext__()`.
   - The generator now raises `UpstreamError` before yielding anything.
   - `create_message` catches it at endpoints.py:265 and returns a real HTTP 502 with the Anthropic envelope, with no `message_start`.
   - `test_zero_chunks_is_a_real_http_502_envelope` pins this.
   - The `except StopAsyncIteration: _empty()` branch (endpoints.py:237) is now unreachable with the real client. It still serves stub clients, and the old `test_empty_stream_still_returns_a_response` is unchanged. Dead-ish code is acceptable and is noted in build.md.

3. (low, docs) The accepted risk is documented honestly in build.md, which says the SDK strips `[DONE]` and that a provider omitting finish_reason will show errors on good replies. It is also in the test module docstring.
   - README.md:21 says the stream ends in an error "including one that ends without a `finish_reason`". That describes the behaviour. It does not warn that a provider which never sends a finish_reason will fail every reply.
   - QUICKSTART has nothing. rework.md scoped README to one sentence, so this is not a defect.
   - Suggested follow-up: one troubleshooting line saying "reply ends with 'Upstream stream ended before a finish_reason was received' means the provider omits finish_reason". Do this before the proxy goes live against the NVIDIA models.

4. (info, correct) Fixes 3 and 4, src/core/errors.py.
   - The surrogate regex `[\ud800-\udfff]` runs after redaction, once, for both the APIError and non-APIError paths.
   - Valid astral characters are intact. I ran `RuntimeError('ok 😀')` and it gave `'Unexpected error: ok 😀 😀'`. A real pair is a single code point in Python str, so the regex cannot touch it.
   - An empty message gives `Unexpected error: RuntimeError`.
   - Minor and unchanged by this fix: `_report_model_error` logs `str(exc)` unsanitised. A surrogate there can only make the logging handler print an internal error. It cannot break the response.

5. (info, tests) Each new test fails on old code per build.md. The mutation runs (6, 3 and 2 failures) are plausible. I checked the assertions and none pass on broken code.
   - The truncation tests assert the absence of `[DONE]`, the exact mapped fields, success count 0 and a single model-error report.
   - The weak spot is that the `empty-delta-no-finish` parametrize case is nearly redundant with `text-then-close`. This is harmless.
   - No test covers `content_filter` explicitly. It is truthy, so it works.
   - `tests/test_midstream_errors.py` has an empty diff, so the byte-identical success test is untouched.

6. (info) The 3.9 fixture fix is only `def hanging` to `async def hanging`, plus a comment. No assertion is changed. The suite passes on 3.9.6.

7. (info, scope) The changed files are exactly the allowed set: README.md, src/core/client.py, src/core/errors.py, tests/test_errors.py, tests/test_endpoints_errors.py and the new tests/test_truncated_stream.py. The unused `Any` import is removed. The README sentence is accurate and makes no claim about Claude Code behaviour.
