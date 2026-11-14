VERDICT: PASS

- Setup: `git archive factory/005-error-contract-a` (24d713c) extracted to /tmp/claude-501/api-a (no `.env` there; `src` resolves to `/private/tmp/claude-501/api-a/src`). Fake stdlib upstream at /tmp/claude-501/api-a-fake/fake.py on 127.0.0.1:18931. Proxy started with `env -i OPENAI_API_KEY=fake-key-1234 OPENAI_BASE_URL=http://127.0.0.1:18931/v1 MAX_RETRIES=0` via `uvicorn src.main:app --port 18932`. Both ports were free before start, and each PID was confirmed as the owner of its listening socket. Each case ran against a fresh proxy process because one 429 puts the only key into cooldown, and the existing exhausted-keys logic on main then answers every later request locally with 429 and 0 upstream calls. That behavior predates this slice and is not a regression.
- Success paths unchanged: non-stream 200 with a valid Anthropic message ("Hello"). Stream 200 with message_start, content_block_start/delta/stop, message_delta and message_stop. 1 upstream call each.
- Non-stream errors: the real status is forwarded and the body is valid JSON `{"detail": "<upstream text unmodified>"}`. 429 with `Retry-After: 7` forwards `retry-after: 7`. The quotes/newlines body comes back as valid JSON: `{"detail":"bad \"thing\" here\nline2 \\ back"}`. No f-string-broken JSON.
- Stream errors: HTTP 200 with message_start, ping, content_block_start and one `event: error` (`{"type":"error","error":{"type":"api_error","message":"Streaming error: UpstreamError"}}`), and no message_stop. This is the deliberate interim behavior until slices C and D. No bare `data: {"error"...}` line appears.
- Key hygiene and cleanup: `fake-key-1234` does not appear in the scratch `logs/proxy.log` or in any captured stdout file. All started PIDs were killed, and 18931 and 18932 were confirmed free at the end. Port 8082 and the main checkout's logs/ and model_contexts_cache.json were not touched.

| Case | Non-stream status | Valid JSON | Upstream text in body | Stream status / events | message_stop | Upstream calls (ns/s) |
|---|---|---|---|---|---|---|
| 200 ok | 200 | yes | n/a ("Hello") | 200 / full sequence | yes | 1/1 |
| 400 | 400 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 401 | 401 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 403 | 403 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 404 | 404 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 422 | 422 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 429 (no Retry-After) | 429, no retry-after | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 429 (Retry-After: 7) | 429, retry-after: 7 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 500 | 500 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 502 | 502 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 503 | 503 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 529 | 529 | yes | yes | 200 / start,ping,cbs,error | no | 1/1 |
| 400 quotes+newlines | 400 | yes | yes (escaped correctly) | 200 / start,ping,cbs,error | no | 1/1 |
