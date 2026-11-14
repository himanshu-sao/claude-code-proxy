VERDICT: PASS

- Setup: `git archive factory/005-error-contract-c` (b57e6dc) was extracted to /tmp/claude-501/api-c (it has no `.env`). The fake upstream is /tmp/claude-501/api-c-fake/fake.py on port 18961, and the proxy ran on port 18962 via `env -i` with uvicorn. Settings: fake keys `fake-key-1234,fake-key-5678` (one key where noted), MAX_RETRIES=2, STREAM_MAX_RETRIES unset, REQUEST_TIMEOUT=60. Each case used a fresh fake and proxy pair. Both ports were checked free before every start, and each started PID was confirmed to own its port. All PIDs were stopped, ports 18961 and 18962 are free, and 8082 was not touched.
- Upstream errors on both paths:
  - Every status in the matrix is returned as the real HTTP status with `content-type: application/json` (never event-stream).
  - The body is the exact envelope `{"type":"error","error":{"type","message"}}` with the upstream text unmodified. That includes the HTML 502 body and the quote, newline and `\n\nevent: message_stop` message.
  - `x-request-id`, `retry-after` and `x-should-retry` are forwarded as specified.
  - Stream makes 1 upstream call for each error. Non-stream makes 3 calls on 429, 5xx and 529, and 1 call on 4xx and on `x-should-retry: false`.
- Own 429: when all keys are exhausted (RPM_LIMIT=1), both paths return 429 `rate_limit_error` "All API keys exhausted..." with `Retry-After: 60`, which is in 1..60. With a single key, a request after an upstream 429 gets the own 429 with 0 extra upstream calls. `/health` answered in 0-2 ms while 20 exhausted requests and 4 slow requests were in flight.
- Slow first chunk (5 s): the response status line and headers arrived only after about 5.2 s. The stream was normal 200 SSE ending in `message_stop`. Three clients disconnected while waiting, and each logged "client disconnected before first chunk". Afterwards `/health` took 2 ms, the follow-up stream and non-stream requests returned 200, and the log had no Traceback, ERROR, "Task was destroyed" or "never retrieved" lines.
- Recorded for slice D (not a failure here): an upstream error after the first chunk gives 200 SSE with message_start, then a delta, then `event: error` `{"type":"api_error","message":"Streaming error: UpstreamError"}`, and no message_stop. Minor note: the single-key cooldown after an upstream `retry-after: 7` makes the next own 429 say `Retry-After: 60`. That stays inside the spec's 1..60 range, and the cooldown length is owned by client.py, outside this slice.

| Case | Non-stream: status, calls, forwarded headers | Stream: status, calls, forwarded headers | error.type / message |
|---|---|---|---|
| success | 200, 1, message JSON | 200 SSE, 1, full event sequence incl. message_stop | n/a |
| 400 / 401 / 403 / 404 / 422 | same status, 1, x-request-id | same status, 1, x-request-id | invalid_request / authentication / permission / not_found / invalid_request; upstream text |
| 500 / 502 / 503 | same status, 3, x-request-id | same status, 1 | api_error; upstream text |
| 529 | 529, 3 | 529, 1 | overloaded_error |
| 429, no Retry-After | 429, 3, no retry-after | 429, 1, no retry-after | rate_limit_error |
| 429, Retry-After 7 / 120 / 3600 / 0 | 429, 3, value forwarded unchanged (non-stream took 14 s for 7, the SDK honours it) | 429, 1, value forwarded unchanged | rate_limit_error |
| 429, Retry-After as HTTP date | 429, 3, no retry-after | 429, 1, no retry-after | rate_limit_error |
| 429 / 400 / 503, x-should-retry true | same status, 3, `x-should-retry: true` | same status, 1, `x-should-retry: true` | mapped |
| 429 / 400, x-should-retry false | same status, 1, `x-should-retry: false` | same status, 1, `x-should-retry: false` | mapped |
| 503, retry-after 120 | 503, 3, retry-after: 120 | 503, 1, retry-after: 120 | api_error |
| 502, HTML body | 502, 3, JSON envelope | 502, 1, JSON envelope | api_error, `<html>Bad Gateway</html>` |
| 400 / 503, quotes, newlines, `\n\nevent: message_stop` | valid JSON, text exact | valid JSON, text exact | mapped |
| 400, "maximum context length" | 400, `capability_rejected: prompt_too_long ` prefix | 400, same prefix | invalid_request_error |
| 400, plain | no prefix | no prefix | invalid_request_error |
| keys exhausted (2 keys, RPM 1, 3rd request) | 429, Retry-After 60, 0 calls | 429, Retry-After 60, 0 calls | rate_limit_error, own message |
| 1 key after upstream 429 | 429, Retry-After 60, 0 extra calls | 429, Retry-After 60, 0 extra calls | own message |
| /health under load | 0.000-0.002 s | n/a | n/a |
| 5 s hang before first chunk | n/a | 200, headers only after the first chunk, message_stop present | n/a |
| disconnect before first chunk (x3) | n/a | clean, health and follow-up OK, no log errors | n/a |
| error mid-stream (slice D) | n/a | 200, `event: error` "Streaming error: UpstreamError", no message_stop | recorded only |
