VERDICT: PASS

Live HTTP test of `factory/005-error-contract-e` @ 655f78a.

**Setup**
- Clean `git archive` copy at /tmp/claude-501/api-e3/. `src` resolved to `/private/tmp/claude-501/api-e3/src/__init__.py`.
- Proxies started with `env -i`, with only these variables: PATH, HOME (scratch), `OPENAI_API_KEY=fake-key-1234,fake-key-5678`, `OPENAI_BASE_URL`, `MAX_RETRIES=2`, `REQUEST_TIMEOUT=5`, `MODEL_FAILURE_THRESHOLD=1000`, `MODEL_HEALTH_CHECK_INTERVAL=3600` and tier models. `STREAM_MAX_RETRIES` was unset.
- The fake upstream (/tmp/claude-501/api-e3-fake/fake.py) is a raw asyncio HTTP server. It picks the case from the first word of the prompt and counts calls per case.
- Ports 8811 (fake), 8812 (main proxy), 8813 (fresh proxy for 429) and 8814 (fresh proxy with `RPM_LIMIT=1`) were checked free first. Each listener PID matched the PID I started: 50582, 50584, 50586, 50588.
- All four were killed by PID, and all four ports were confirmed free afterwards.
- I did not touch port 8082 (the user's proxy, PID 1848, still running), the main checkout's logs/ or its model_contexts_cache.json. The copy wrote its own logs/ and cache.

**Streaming matrix** (`stream:true`, through the real proxy, 1 upstream call per case)

| # | upstream behaviour | HTTP | events in order | error type / message |
|---|---|---|---|---|
| 1 | 2 chunks, clean chunked close, no finish_reason, no [DONE] (the fixed bug) | 200 | message_start, content_block_start, ping, delta, delta, **error** | exactly 1 error, nothing after it: no content_block_stop, message_delta or message_stop. `api_error` "Upstream stream ended before a finish_reason was received" |
| 2 | 0 chunks, clean close | **502**, application/json | none. There is no SSE and no message_start | envelope `{"type":"error","error":{"type":"api_error","message":"Upstream stream ended before a finish_reason was received"}}` |
| 3a | finish `stop`, no usage chunk, no [DONE] | 200 | start, block_start, ping, delta x2, block_stop, message_delta (end_turn), message_stop | no error |
| 3b | `stop`, usage-only chunk, no [DONE] | 200 | same as 3a | no error |
| 3c | `stop`, no usage chunk, with [DONE] | 200 | same as 3a | no error |
| 3d | `stop`, usage chunk, with [DONE] (also the default "ok" stream) | 200 | same as 3a | no error |
| 3e | `length`, without usage chunk, with [DONE] | 200 | same as 3a | stop_reason `max_tokens` |
| 3f | `length`, with usage chunk, no [DONE] | 200 | same as 3a | stop_reason `max_tokens` |
| 3g | `tool_calls`, with a tool call, usage chunk, [DONE] | 200 | ..., delta, block_start (tool_use), delta, block_stop, block_stop, message_delta, message_stop | stop_reason `tool_use` |
| 3h | `tool_calls`, no usage chunk, no [DONE] | 200 | same as 3g | stop_reason `tool_use` |
| 3i | `content_filter`, [DONE], no usage chunk | 200 | normal ending with message_stop | stop_reason `end_turn` |
| 3j | `content_filter`, usage chunk, no [DONE] | 200 | normal ending with message_stop | stop_reason `end_turn` |
| 4 | 3 chunks, finish_reason null on all, then `data: [DONE]` | 200 | start, block_start, ping, delta x3, **error** | 1 error, no message_stop. Error `api_error` "Upstream stream ended before a finish_reason was received". |
| 5b | stream, 400 before the first chunk, message `bad \ud800 text` | 400 | none (JSON) | `invalid_request_error`, message `bad � text` (valid JSON, valid UTF-8) |
| 5c | surrogate in an error frame after 2 chunks | 200 | ..., delta x2, **error** | exactly 1 valid event, `api_error`, `bad � text` |
| 6 | RST after 2 chunks | 200 | ..., delta x2, **error** | `api_error` "Unexpected error: ReadError" (no longer an empty tail) |

- Case 4 (accepted risk): a provider that sends only `[DONE]` and never a finish_reason now gets a truncation error on a complete reply.
- Case 4 and a clean close are identical at this layer. The fake sent a real `data: [DONE]` line and the result was the same error as case 1.
- Case 4 is the expected behaviour from the build.
- I did not test any real provider.
- The 5b message was sent in the JSON as `\ud800` and came back as `�`.

**Surrogate, non-stream**
- Request: `POST /v1/messages`, `stream:false`, upstream 400 with the lone surrogate.
- Result: 400, `invalid_request_error`, `bad � text`. This is the real 400, not a 500.
- Upstream calls: 1.

**Regression**

| check | result |
|---|---|
| stream success | 200, ends in message_stop, 1 call |
| non-stream success | 200, full message, `end_turn`, 1 call |
| 400, stream and non-stream | real 400, `invalid_request_error`, 1 call each |
| 503, non-stream | 503 `api_error` envelope, 3 calls (MAX_RETRIES=2) |
| 503, stream | 503 `api_error` envelope, 1 call |
| 429 with `Retry-After: 7`, stream (fresh proxy) | 429, `rate_limit_error`, `retry-after: 7`, 1 call |
| 429 with `Retry-After: 7`, non-stream (same proxy, second request) | 429, `retry-after: 7`, 3 calls |
| `RPM_LIMIT=1`, 2 keys, after the keys were used up | stream and non-stream both 429 `rate_limit_error` "All API keys exhausted...", `Retry-After: 12` (integer, within 1..60), 0 upstream calls |
| `/health` on the exhausted proxy | 200 immediately |
| `/health` on the main proxy after the disconnect cases | 200 |
| non-stream with zero chunks or no finish_reason | not applicable. Those are stream-only paths, and the fake returns a normal JSON body for non-stream |

**Disconnects**
- Disconnect before the first chunk (upstream `hang`): the log shows `client disconnected before first chunk`. A follow-up stream returned 200, and `/health` was fine.
- Disconnect mid-stream (upstream stalled after 2 chunks, client closed after 1.5 s): the log shows `Client disconnected, cancelling request`. A follow-up stream returned 200, and `/health` was fine.
- `Task was destroyed` and `never retrieved` appear in none of the 4 proxy logs. Neither does the Python-level `Traceback` in the rpm and p429 logs.

**Keys**
- No fake key appeared in any response body. The scan looked for `fake-key` and `1234` near "key".
- The full `fake-key-1234` and `fake-key-5678` strings appear in none of the four proxy logs or in fake.log.
- The p429 log contains only the existing `fake-key...` prefix in the "Penalizing" warning.

**Minor, non-blocking finding**
- The main proxy log has 2 `--- Logging error ---` blocks. Each has a `UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800'` inside `_report_model_error` (client.py:241, `_log.warning`).
- The log line interpolates the raw `str(exc)` of the upstream error, which still holds the surrogate. A logging handler fails to write it.
- This is logging-module noise only. The client responses were correct, and the HTTP result in cases 5b and 5c and the non-stream case is unaffected.
- This matches the "out of scope" list in rework.md (`str(e)` logging). I mention it only because my "no Traceback" scan counts it. The main log also has those 4 `Traceback` lines, and all four are inside these two blocks.
- Fix idea: sanitise the string in the log call.

**Not tested**
- Any real provider, including whether providers send finish_reason on every reply (the accepted risk).
- How Claude Code displays the 502 or the mid-stream `event: error`.
- Python 3.9 (the live run used the 3.14 venv).
- `active_requests` leaks, which are not visible over HTTP. Indirect evidence only: follow-up requests and `/health` were fine.
- Azure path, model-fallback switching, `STREAM_MAX_RETRIES` and a soak run. I did not re-run these, because the change does not touch them.
