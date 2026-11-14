VERDICT: PASS

- Setup: `git archive factory/005-error-contract-a` (3b84a81) extracted to /tmp/claude-501/api-a2. It has no `.env`. I started it with `env -i` (OPENAI_API_KEY fake, MAX_RETRIES=0, HOST=127.0.0.1) via `uvicorn src.main:app` on port 18942. The fake upstream is /tmp/claude-501/api-a2-fake/fake.py on port 18941. Both ports were free before each start. Each started PID was confirmed to own its port with lsof. Every case ran on a fresh proxy process, except the disconnect test, which used one. All PIDs were killed at the end. Ports 18941 and 18942 are free. Port 8082 (the user's proxy) was never touched. The main checkout's logs/ and model_contexts_cache.json were not written.
- Key length: redaction ignores keys shorter than 8 characters (MIN_REDACT_KEY_LEN). The test keys `fake-key-1234` and `fake-key-5678` are 13 characters, so they are covered.
- Round-1 matrix repeated, no regressions:
  - Non-stream success returns 200 with a valid message.
  - Stream success returns the full event sequence.
  - Each non-stream error forwards the real status, with the upstream text in `{"detail": ...}` and exactly 1 upstream call.
  - 429 with `Retry-After: 7` forwards `retry-after: 7`. 429 without it has no header.
  - The quotes/newlines body is valid JSON: `{"detail":"bad \"thing\" here\nline2 \\ back"}`.
  - Stream errors for 400, 429r, 503, quote and echo return HTTP 200, one `event: error` ("Streaming error: UpstreamError") and no `message_stop`. No bare `data: {"error"` line appears. This is the expected interim behavior until slices C and D.
- NEW (a), hostile headers:
  - Upstream 429 sent raw UTF-8 `retry-after: ٣` and `x-request-id: réq-ü`. The proxy returned 429 with `{"detail":"upstream-msg-nonascii"}` and dropped both headers.
  - Upstream 500 sent non-ASCII `x-request-id` and `retry-after: 5é`. The proxy returned 500 with the real body.
  - Upstream 503 sent raw latin-1 bytes `\xe9\xff` in `x-request-id` and `retry-after`, plus a valid `request-id: ok-id-1`. The proxy returned 503 with the real body, forwarded `request-id: ok-id-1` and dropped the bad headers. There was no plain-text 500 in any of the three.
- NEW (b), key redaction:
  - With one key, the upstream echoed `fake-key-1234` in its 400 message. The response was `{"detail":"invalid api key [redacted] supplied"}`.
  - With two keys, the upstream echoed the other key. This ran 3 times, so round-robin gave both keys as the sender. Every run returned `leaked other [redacted] here`. The two-key echo of the sending key was also redacted, in both non-stream and stream mode.
  - `grep fake-key-` returns 0 hits in the scratch `logs/proxy.log` and in all captured proxy stdout files. The health endpoint only shows `fake-key...`, which is a prefix and not a key.
- NEW (c), client disconnect:
  - I sent 3 non-stream requests to a case where the fake upstream sleeps 4 seconds, and each curl timed out at 1 second (rc=28).
  - After the sleeps finished, `/health` answered and a follow-up request returned 200 "Hello".
  - The log shows no ERROR, Traceback, "Task was destroyed" or "never retrieved" lines in that window. The only lines are the 3 request logs and the 3 completed upstream 200s.
  - The proxy does not abort the upstream call when the client leaves. It lets the call finish quietly, and nothing hangs.

| Case | Non-stream status | `detail` = upstream text | Upstream calls | Stream result |
|---|---|---|---|---|
| ok | 200 | n/a | 1 | 200, full sequence with message_stop |
| 400 | 400 | yes | 1 | 200, error event, no message_stop |
| 401 | 401 | yes | 1 | not run, covered in round 1 |
| 403 | 403 | yes | 1 | not run, covered in round 1 |
| 404 | 404 | yes | 1 | not run, covered in round 1 |
| 422 | 422 | yes | 1 | not run, covered in round 1 |
| 429 (no Retry-After) | 429, no retry-after | yes | 1 | not run, covered in round 1 |
| 429 (Retry-After: 7) | 429, retry-after: 7 | yes | 1 | 200, error event, no message_stop |
| 500 | 500 | yes | 1 | not run, covered in round 1 |
| 502 | 502 | yes | 1 | not run, covered in round 1 |
| 503 | 503 | yes | 1 | 200, error event, no message_stop |
| 529 | 529 | yes | 1 | not run, covered in round 1 |
| 400 quotes/newlines | 400, valid JSON | yes | 1 | 200, error event, no message_stop |
| non-ASCII headers (429, 500) | real status | yes | 1 | not run |
| latin-1 header bytes (503) | real status, `request-id` kept | yes | 1 | not run |
| key echo (1 key) | 400, `[redacted]` | yes | 1 | 200, error event |
| other-key echo (2 keys, x3) | 400, `[redacted]` | yes | 1 | not run |
| client disconnect (x3) | n/a | n/a | 3 | n/a, no log errors, proxy healthy |
