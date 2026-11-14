VERDICT: CHANGES

Integration live test of `factory/005-error-contract` @ 1cff272 (slices A+B+C+D). Clean `git archive` copy at /tmp/claude-501/api-whole/ (`src` resolved to `/private/tmp/claude-501/api-whole/src/__init__.py`, no `.env` in or above it). Started with `env -i` and only `OPENAI_API_KEY=fake-key-1234,fake-key-5678`, `OPENAI_BASE_URL=http://127.0.0.1:8781/v1`, `MAX_RETRIES=2`, `REQUEST_TIMEOUT=5`, `MODEL_FAILURE_THRESHOLD=1000`, `MODEL_HEALTH_CHECK_INTERVAL=3600`, and tier models. `STREAM_MAX_RETRIES` was unset unless noted. The fake upstream was a raw asyncio HTTP server (/tmp/claude-501/api-whole-fake/fake.py) selected per case by the first word of the prompt. It counted calls per case. Ports 8781-8785 were free before start, each listener PID matched the PID I started, and all were stopped and free at the end. Port 8082, the main checkout's logs/ and its model_contexts_cache.json were not touched. A fresh proxy process was used per status case.

## Blocking finding

**Two chunks, then a clean close without `[DONE]` and without `finish_reason`, becomes a fake successful turn.**
- Request: `POST /v1/messages` `{"model":"claude-sonnet-4","max_tokens":200,"stream":true,"messages":[{"role":"user","content":"ms_close hi"}]}`. The upstream sends 200 SSE, `Hel`, `lo`, then the zero-length chunk terminator (no `[DONE]`, no `finish_reason`).
- Observed: HTTP 200 with `message_start, content_block_start, ping, content_block_delta x2, content_block_stop, message_delta(stop_reason=end_turn), message_stop`. There is no `event: error`.
- Expected (task matrix, brief 3.4.4 "never a fake successful end"): exactly one `event: error` and no `message_stop`.
- Cause: `src/core/client.py` `create_chat_completion_stream` always yields `data: [DONE]` once the SDK iterator ends. It cannot tell a real `[DONE]` from a truncated body, and the converter then emits the normal end. Suggested fix: track whether any chunk carried a `finish_reason` (or whether `[DONE]` was seen). If neither happened, raise a mapped mid-stream `UpstreamError`.
- A non-clean close (body cut mid-chunk) is handled correctly. See `ms_fin` below.

## Pre-first-byte contract (MAX_RETRIES=2, STREAM_MAX_RETRIES unset)

All rows below are the same for `stream:false` and `stream:true` except for the call count. Every response had content-type `application/json` and body `{"type":"error","error":{"type","message"}}`.

| upstream case | status (ns / s) | error.type | error.message | forwarded headers | upstream calls ns / s |
|---|---|---|---|---|---|
| 400 | 400 / 400 | invalid_request_error | `bad request upstream` (unmodified) | none | 1 / 1 |
| 401 (text contains both pool keys) | 401 / 401 | authentication_error | `Incorrect API key provided: [redacted] and [redacted]` | none | 1 / 1 |
| 403 | 403 / 403 | permission_error | unmodified | none | 1 / 1 |
| 404 | 404 / 404 | not_found_error | unmodified | none | 1 / 1 |
| 422 | 422 / 422 | invalid_request_error | unmodified | none | 1 / 1 |
| 429 `Retry-After: 7` | 429 / 429 | rate_limit_error | `slow down` | `retry-after: 7` | 3 / 1 |
| 429 no Retry-After | 429 / 429 | rate_limit_error | unmodified | none | 3 / 1 |
| 429 `Retry-After: 120` | 429 / 429 | rate_limit_error | unmodified | `retry-after: 120` (passed through, not capped) | 3 / 1 |
| 429 HTTP-date Retry-After | 429 / 429 | rate_limit_error | unmodified | dropped (as specified) | 3 / 1 |
| 500 | 500 / 500 | api_error | unmodified | none | 3 / 1 |
| 502 | 502 / 502 | api_error | unmodified | none | 3 / 1 |
| 503 | 503 / 503 | api_error | unmodified | none | 3 / 1 |
| 529 | 529 / 529 | overloaded_error | unmodified | none | 3 / 1 |
| 400 + `x-should-retry: true` | 400 / 400 | invalid_request_error | unmodified | `x-should-retry: true` | 3 / 1 (SDK honours the header) |
| 503 + `x-should-retry: false` + `request-id` | 503 / 503 | api_error | unmodified | `x-should-retry: false`, `request-id: req_abc123` | 1 / 1 |
| HTML 502 body | 502 / 502 | api_error | `<html><body><h1>502 Bad Gateway</h1></body></html>` in valid JSON | none | 3 / 1 |
| 400 with quotes, newlines and `\n\nevent: message_stop` | 400 / 400 | invalid_request_error | exact text, valid JSON, no injected event | none | 1 / 1 |
| 400 `maximum context length ...` | 400 / 400 | invalid_request_error | `capability_rejected: prompt_too_long This model's maximum context length is 8192 tokens...` | none | 1 / 1 |
| plain 400 `invalid field foo` | 400 / 400 | invalid_request_error | `invalid field foo` (no prefix) | none | 1 / 1 |
| first chunk never arrives (`REQUEST_TIMEOUT=5`) | - / 500 after 5.2 s | api_error | `Request timed out.` | none | - / 1 |

## Mid-stream matrix (real server, stream:true)

| case | HTTP | events | `event: error` count | anything after error | upstream calls | key in body/log | follow-up stream + /health |
|---|---|---|---|---|---|---|---|
| success | 200 | message_start, content_block_start, ping, delta x3, content_block_stop, message_delta, message_stop | 0 | - | 1 | no | ok |
| 2 chunks then RST | 200 | ..., delta x2, error | 1 | none | 1 | no | 200 message_stop / 200 |
| 2 chunks then clean close, no [DONE] | 200 | ..., delta x2, content_block_stop, message_delta, **message_stop** | **0** | - | 1 | no | ok (**FAIL**, see above) |
| 2 chunks then cut mid-chunk (`ms_fin`) | 200 | ..., delta x2, error (`peer closed connection ... incomplete chunked read`) | 1 | none | 1 | no | ok |
| 2 chunks then stall past REQUEST_TIMEOUT=5 | 200 | ..., delta x2, error after 5.0 s | 1 | none | 1 | no | ok |
| tool-call delta (block started) then RST | 200 | ..., delta x2, content_block_start(tool_use), error | 1 | none | 1 | no | ok |
| hostile error text after first chunk | 200 | ..., error | 1 (text JSON-escaped in one `data:` line) | none | 1 | no | ok |
| upstream error echoing both pool keys | 200 | ..., error `leak [redacted] and [redacted]` | 1 | none | 1 | no (log also redacted) | ok |

Minor, non-blocking: for RST, stall and tool-then-RST, the event message is `"Unexpected error: "` with empty text. The exception string is empty, so the client gets no hint such as "connection reset" or "timed out". Shape and type (`api_error`) are correct.

## Other checks

| check | result |
|---|---|
| Success non-stream | 200, full Anthropic message, `stop_reason: end_turn` |
| All keys exhausted (`RPM_LIMIT=1`, 2 keys) | 3rd and 4th requests: 429 `rate_limit_error` "All API keys exhausted...", `Retry-After: 60` (integer, within 1..60) for both non-stream and stream. 10 concurrent exhausted requests all returned 429, with 0 extra upstream calls |
| `/health` while exhausted | 5 calls during the concurrent burst: 200 in 0-3 ms |
| `STREAM_MAX_RETRIES=2` (separate process) | stream 503 = 3 upstream calls, stream 400 = 1 |
| `STREAM_MAX_RETRIES=abc` | starts. Log: `Invalid STREAM_MAX_RETRIES='abc'; using 0`. Stream 503 = 1 call, normal stream ok |
| Client disconnect before first chunk (upstream hangs) | upstream TCP connection closed within 1.5 s. Log: `client disconnected before first chunk`. /health ok |
| Client disconnect mid-stream (upstream stalled, REQUEST_TIMEOUT=60) | upstream connection closed within 1 s. /health ok. Follow-up stream and non-stream 200 |
| Soak: 50 concurrent mixed (ok s/ns, 503 s/ns, RST, tool+RST, slow) | all as expected: 15x 200 message_stop/message, 14x 503 envelope, 14x 200 ending with a single error. 503 non-stream = 3 calls each, stream = 1 (28 total for 7+7). /health 200 during (67 ms) and after (1 ms) |
| Logs (all 4 scratch proxy logs + copy's logs/proxy.log) | 0 `Traceback`, 0 `Task was destroyed`, 0 `never retrieved`, 0 `Unexpected error processing`, 0 occurrences of either fake key. Only ERROR lines are the expected `Mid-stream upstream error: status=500` |

## Not tested
- `active_requests` is not exposed over HTTP, so I could not observe leaks directly. Indirect evidence: upstream sockets close on disconnect, and no stuck requests or warnings appeared after the soak.
- A real Claude Code session (G15: what the CLI shows for a pre-stream 400, 429 countdown, 503 retries, a mid-stream `event: error`, and whether auto-compact triggers on the prompt_too_long prefix). This was not run.
- `anthropic-ratelimit-unified-*` and `x-request-id` forwarding over HTTP (only `request-id` was exercised), the Azure path, and model-fallback switching (threshold was raised to 1000 to keep cases independent).
- Real NVIDIA upstream (not run, needs the user's go-ahead).
