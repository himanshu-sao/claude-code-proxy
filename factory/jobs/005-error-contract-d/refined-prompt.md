# Refined prompt (slice D of 005-error-contract)

Parent job: `005-error-contract`. Integration branch: `factory/005-error-contract` (cut from feat/virtual-auto-model at 67de01a). Read `factory/jobs/005-error-contract/answers.md` and `brief.md` too.

## Refined prompt
One error contract across the proxy, run as a normal factory job split into 4 sub-jobs. Each sub-job carries its own tests and docs and must pass `uv run black src/ && uv run isort src/` (line-length 100) before handback. Offline suite: `.venv/bin/python -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider` with `OPENAI_API_KEY=test-key`, run from the job worktree (baseline 377 passed, 4 xfailed). Never run tests from the main checkout.

Shared mapping: `src/core/errors.py` turns an upstream exception into `(status, anthropic_type, message, forwarded_headers, retryable, counts_as_model_failure)`, and builds the envelope with `json.dumps`.

### D: mid-stream error event and xfail cleanup
- **Summary:** `src/conversion/response_converter.py` `convert_openai_streaming_to_claude_with_cancellation`: on an error after the first chunk, emit `event: error` (built by A's envelope builder) and return without `message_stop`. Hostile upstream text cannot create extra SSE events. Remove the four strict xfail markers and reason text on `test_stream_upstream_error_is_visible_to_client[400|422|503|429]`; update `test_stream_upstream_error_counts_as_model_failure_only_for_503_and_429` and the old `detail` assertions. Update QUICKSTART error notes if they describe the old shape.
- **Files (3):** `src/conversion/response_converter.py`, `tests/test_job003_endpoints.py`, `QUICKSTART.md`.
- **Depends on:** A (builder), C (stream pre-read interface).
- **Owns goals:** G3, G4, G6, G12 (final gate: the full offline suite with baseline numbers; the success path is unchanged).
- **Owns edge cases:** 6, 7.
- **Definition of done:** the four xfails pass with markers removed; `event: error` present and no `message_stop` after a mid-stream failure; success-path SSE output byte-identical to before for a fixture stream; format passes.

## Orchestrator constraints for this slice
- Starts only after A, B and C are merged into the integration branch `factory/005-error-contract`.
- Success-path SSE output must be byte-identical to before for a fixture stream (add that test).
- Remove the xfail markers only when the tests genuinely pass; do not weaken their assertions.

## Assumptions
1. CONFIRMED. Error body is `{"type":"error","error":{"type":<anthropic type>,"message":<upstream text>}}`, reusing the envelope pattern from `src/api/compat.py`. `/v1/messages` errors stop using `{"detail": ...}`.
2. CONFIRMED. Status to type: 400 invalid_request_error, 401 authentication_error, 403 permission_error, 404 not_found_error, 413 request_too_large, 429 rate_limit_error, 500 api_error, 529 overloaded_error. Other 4xx map to invalid_request_error (status kept), other 5xx to api_error (status kept).
3. CONFIRMED. Message is the upstream text unmodified. Context-length rejections get the prefix `capability_rejected: prompt_too_long ` in front of the upstream text. Docs (errors.md 2434-2460) say the token is what a Claude apps gateway emits and Claude Code treats it like `Prompt is too long`. Whether a proxy-built message triggers auto-compact is NOT VERIFIED; checked in live verification.
4. CONFIRMED (to verify live). Whether Claude Code shows the message of an Anthropic `event: error` is NOT VERIFIED.
5. CONFIRMED. Forwarded headers: upstream `retry-after` (integer seconds, passed through unchanged, including values above 60), `x-should-retry` (unchanged), `request-id`/`x-request-id` if present, `anthropic-ratelimit-unified-*` (unchanged). An HTTP-date or non-integer upstream `retry-after` is dropped.
6. CONFIRMED. Our own 429 (all local keys exhausted) gets `Retry-After` as an integer 1..60 via `config.seconds_until_key_available()`. This is the only value capped at 60.
7. CONFIRMED. Every streamed request reads the upstream's first chunk before the `StreamingResponse` headers are sent. Errors before the first chunk return a real HTTP status with the Anthropic body and forwarded headers.
8. CONFIRMED. Mid-stream errors (after the first chunk) emit `event: error` and no `message_stop`. No mid-stream retry.
9. CONFIRMED. `STREAM_MAX_RETRIES` (default 0, non-negative integer) overrides the SDK `max_retries` for streamed upstream calls only. `MAX_RETRIES` (default 2) still applies to non-stream. Documented in `.env.example` and README "Environment Variables".
10. CONFIRMED. Fallback accounting in `OpenAIClient._report_model_error` keeps the current rule set (429, 503, rate_limit, model not found/does not exist/unavailable, overloaded, capacity count; 400 does not). The rule now lives in the shared mapping function.
11. CONFIRMED. Tests asserting the old `detail` envelope and the 200 stream status are updated to the new contract. This is expected, not a regression.

## Goals (verified by the slice in brackets)
- G1 [C] Non-stream and stream upstream 400, 401, 403, 404, 422, 500, 502, 503, 529 each return the same HTTP status and an Anthropic body whose `error.message` equals the upstream text (plus the prompt-too-long prefix where applicable).
- G2 [C] Upstream 429 with and without `retry-after` returns 429 with the same body; `retry-after` is forwarded when present.
- G3 [D] The four xfails (400, 422, 503, 429) pass with markers removed.
- G4 [D] Mid-stream failure emits `event: error` with `error.type` `api_error` and no `message_stop`.
- G5 [A] An error built from a message with `"` and newlines parses as valid JSON.
- G6 [D] A hostile upstream error text (for example containing `\n\nevent: message_stop`) produces exactly one `event:` line for the error.
- G7 [C] Our own 429 has `Retry-After` as an integer in 1..60. Upstream `retry-after` is passed through unchanged, including values above 60.
- G8 [C] Exhausted keys return 429 for stream and non-stream, never 500 or a `null` body.
- G9 [C] While keys are exhausted, a concurrent `GET /health` returns within 100 ms.
- G10 [C] Stream makes 1 upstream call on 503 with `STREAM_MAX_RETRIES=0`; non-stream makes up to 3 with `MAX_RETRIES=2`.
- G11 [A] Fallback accounting: a 503 counts once per client request on both paths, a 400 never counts.
- G12 [D] Success-path responses are unchanged; offline suite passes at the baseline (377 passed, 4 xfailed before the xfail removal).
- G13 [done, regression] `logs/proxy.log` is not truncated on import.
- G14 [B] `STREAM_MAX_RETRIES` is in `.env.example` and README with default 0.
- G15 [orchestrator, live] See the live verification section.

## Edge cases (each owned by one slice)
1. [A] Empty upstream error body or message.
2. [C] Upstream `retry-after` absent, HTTP-date, non-integer, `0`, or negative.
3. [C] Upstream `x-should-retry` `true` and `false` pass through unchanged.
4. [C] First chunk never arrives (upstream hangs until `REQUEST_TIMEOUT`).
5. [C] Client disconnects while waiting for the first chunk: upstream cancelled, `active_requests` entry removed.
6. [D] Error after a tool call has started: block-stop ordering stays valid.
7. [D] `[DONE]` with no finish reason.
8. [A] Azure client path (`api_version` set) gets the same mapping.
9. [C] Multiple keys: one key 429s, the next succeeds; the client sees no error; only the failed key is accounted.
10. [C] All keys exhausted on a retry: 429 returned before the first byte.
11. [A] Model fallback switch mid-sequence (threshold 3); the error path reports correctly.
12. [B] `STREAM_MAX_RETRIES` negative, non-integer, or non-zero (for example 2) values: negative and non-integer fall back to 0 with a warning; non-zero is honoured.
13. [A] Prompt-too-long: a context-length 400 gets the token prefix; other 400s do not.
14. [A] Upstream 401 message does not expose the API key.
15. [C] Non-JSON upstream body (HTML 502 page): the response is still valid Anthropic JSON.

## Interface facts from merged slices A, B and C (orchestrator, verified at 6c82d50)
- Branch `factory/005-error-contract-d` is cut from the integration branch `factory/005-error-contract` at 6c82d50 (A, B and C merged). Read code with `git show factory/005-error-contract:<path>` or from the worktree `.claude/worktrees/005-int` (it is on 6c82d50).
- G3 is ALREADY DONE by slice C (the four strict xfail markers were removed and the tests pass). Slice D owns G4, G6, G12 and edge cases 6 and 7; it does NOT touch the xfail markers.
- In `src/api/endpoints.py` the converter now receives `_prepend(first_chunk, gen)` or `_empty()` for the stream. The outer handler no longer covers the stream body. An `UpstreamError` raised AFTER the first chunk surfaces inside the converter's `async for` in `convert_openai_streaming_to_claude_with_cancellation`; today its generic `except Exception` emits `Streaming error: UpstreamError`. D must catch `UpstreamError` there, read `e.mapped` (status, error_type, message, headers...), and emit one Anthropic `event: error` built with `src.core.errors.error_json` / `error_envelope`, then end the stream WITHOUT `message_stop` (no `message_delta`, no `message_stop`, and do not fake a successful ending). Keep the cancellation path (HTTPException 499) behaviour.
- Mid-stream error `type`: use `e.mapped.error_type` (for example `rate_limit_error`, `overloaded_error`, `api_error`), message = `e.mapped.message` (already redacted by A). Non-UpstreamError exceptions keep a generic `api_error` event with a SAFE message (type name only, never the raw exception text).
- Hostile upstream text must not create extra SSE events: JSON-encode with `json.dumps` (newlines become `\n` inside the JSON string), exactly one `event: error` block per failure.
- Block-closing question for edge case 6 (error after a tool call has started): decide whether to emit `content_block_stop` for the open block before the error event; Claude Code treats a body that ends after a block started but before `message_delta` as a dropped connection, and `event: error` is the documented signal. State the decision in the spec and test it.
- Accounting already happens exactly once inside the client; the converter must NOT report model errors again.
- Success-path SSE output must be byte-identical to before for a fixture stream (add that test: capture the converter's output for a fixed fixture BEFORE the change from the baseline commit and assert equality).
- The 4 old strict xfail tests are plain passing tests now; do not weaken them.
- Doc work for this slice: QUICKSTART error notes (and README features list if it describes errors); STREAM_MAX_RETRIES is already documented.
- Known non-blocking follow-ups (do not fix here): `count_tokens` and `/test-connection` return `str(e)` in their error detail; a trickling upstream can hold a worker (no total first-chunk deadline); ESC and U+2028 not escaped in the client warning log.
