# Refined prompt (slice C of 005-error-contract)

Parent job: `005-error-contract`. Integration branch: `factory/005-error-contract` (cut from feat/virtual-auto-model at 67de01a). Read `factory/jobs/005-error-contract/answers.md` and `brief.md` too.

## Refined prompt
One error contract across the proxy, run as a normal factory job split into 4 sub-jobs. Each sub-job carries its own tests and docs and must pass `uv run black src/ && uv run isort src/` (line-length 100) before handback. Offline suite: `.venv/bin/python -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider` with `OPENAI_API_KEY=test-key`, run from the job worktree (baseline 377 passed, 4 xfailed). Never run tests from the main checkout.

Shared mapping: `src/core/errors.py` turns an upstream exception into `(status, anthropic_type, message, forwarded_headers, retryable, counts_as_model_failure)`, and builds the envelope with `json.dumps`.

### C: endpoints: non-stream path and pre-first-byte stream
- **Summary:** `src/api/endpoints.py` `create_message`: non-stream returns the mapped status, the Anthropic body and forwarded headers via `JSONResponse`. Stream obtains the client with `stream=True`, starts the upstream stream, awaits the first chunk; on failure returns the mapped HTTP error with headers; on success returns `StreamingResponse` with the first chunk re-prepended. Disconnect while waiting cancels the upstream and clears `active_requests`. Exhausted keys stay 429 (T1 behaviour).
- **Files (3):** `src/api/endpoints.py`, `tests/test_endpoints_errors.py` (new), `src/core/client.py` only if a first-chunk helper is needed (must be coordinated with A; A is done before C starts). Target: 2 files.
- **Depends on:** A, B.
- **Owns goals:** G1, G2, G7, G8, G9, G10.
- **Owns edge cases:** 2, 3, 4, 5, 9, 10, 15.
- **Definition of done:** status matrix for stream and non-stream (400, 401, 403, 404, 422, 500, 502, 503, 529, 429 with and without `retry-after`) with identical status and body text; upstream call counts (stream 1 on 503 with `STREAM_MAX_RETRIES=0`; non-stream up to 3 with `MAX_RETRIES=2`); a concurrent `/health` answers within 100 ms while keys are exhausted; format passes.

## Orchestrator constraints for this slice
- Starts only after A and B are merged into the integration branch `factory/005-error-contract`.
- When `endpoints.py` starts calling `get_next_client_async(stream=True)`, the existing test stubs that patch it with zero-argument functions (`tests/test_endpoints.py::stub_upstream`, `tests/test_job003_endpoints.py` helpers, `tests/test_exhausted_keys.py::exhausted`) will break. Update them to accept `stream=False` as a keyword argument. This is part of this slice.
- Request-handler code must never call the sync `config.get_next_client()`.
- Do NOT edit `src/conversion/response_converter.py` (slice D owns it).

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

## Interface facts from merged slices A and B (orchestrator, verified against the merged code at a9bc904)
- Branch `factory/005-error-contract-c` is cut from the integration branch `factory/005-error-contract` at a9bc904, which already contains A (src/core/errors.py, client.py refactor) and B (`STREAM_MAX_RETRIES`, `get_next_client_async(*, stream=False)`).
- Non-stream: `OpenAIClient.create_chat_completion` raises `UpstreamHTTPError`, which is an `HTTPException` subclass carrying `.mapped` (a `MappedError`: status, error_type, message, headers, retryable, counts_as_model_failure). The unchanged endpoint currently renders it as `{"detail": message}`; this slice must render the Anthropic envelope `{"type":"error","error":{...}}` via `error_json`/`error_envelope` with the mapped headers.
- Stream: `create_chat_completion_stream` is an async generator; the upstream call and any error happen on the FIRST `__anext__`, not when the method is called, and `active_requests` is set up at that point too. It raises a plain `UpstreamError` (NOT an `HTTPException`) carrying `.mapped`. `UpstreamError` has no `status_code`. This slice must prime the first chunk before returning `StreamingResponse`, and on `UpstreamError` return a real HTTP error built from `e.mapped`.
- A forwarded upstream `retry-after` is NOT capped at 60 (user decision: pass through). Only OUR OWN 429 (all local keys exhausted) is capped, via `config.seconds_until_key_available()` (already used by endpoints.py).
- Accounting (`_report_model_error`) already happens exactly once per client call inside the client; endpoints must not report again.
- Existing test stubs that patch `config.get_next_client_async` with zero-argument functions break once endpoints call it with `stream=True`; update them to accept `stream=False` as a keyword (tests/test_endpoints.py `stub_upstream`, tests/test_job003_endpoints.py helpers around lines 70-80 and 384, tests/test_exhausted_keys.py `exhausted`).
- Existing tests that assert the old `{"detail": ...}` body for non-stream errors will need updating to the Anthropic envelope; list each one in build.md.
- Scratch-proxy lesson: a single key goes into cooldown after its first upstream 429, so later requests get a local 429 with 0 upstream calls. Tests that exercise several upstream 429s must account for that (several keys, or reset the penalty).
- Known non-blocking follow-ups from A (do not fix here): ESC and U+2028 are not escaped in the client warning log; one weak cancellation test.
