VERDICT: PASS

- `git diff --stat 50c2be1 factory/005-error-contract-d -- src` prints nothing, so src/ is unchanged. Tip is 1e99bd1.
- Setup: `git archive` was extracted to /tmp/claude-501/api-d2. The fake upstream (fake.py copied from round 1) is in /tmp/claude-501/api-d2-fake on port 18981 and the proxy runs on port 18982. Both ports were free before start, and each PID I started owned its port. The proxy ran under `env -i` with fake keys and MAX_RETRIES=2 and loaded no `.env`. I stopped both processes by PID and both ports are free. Port 8082 (PID 1848) was not touched, and nothing was written into the main checkout apart from this file.

| # | Case | Observed |
|---|---|---|
| 1 | Success stream | 200. Events end `content_block_stop`, `message_delta`, `message_stop`. |
| 2 | 2 chunks, then upstream SSE error | 200. After the 2 deltas there is exactly one `event: error` (`api_error`, "upstream exploded mid-stream"), with no `message_stop`. 1 upstream call. |
| 3a | Pre-first-chunk 503, stream | Real 503, `application/json`, body `{"type":"error","error":{"type":"api_error","message":"svc down"}}`. 1 upstream call. |
| 3b | Pre-first-chunk 503, non-stream | Real 503 with the same envelope. 3 upstream calls (SDK retries, as in round 1). |
| 4a | Invalid body `{"model":"x"}` | 422 with `{"detail":[...]}`, which matches the new QUICKSTART text. |
| 4b | Proxy ANTHROPIC_API_KEY set, wrong key sent | 401 with `{"detail":"Invalid API key. Please provide a valid Anthropic API key."}`, which matches the new QUICKSTART text. |

- The proxy log contains no fake key strings.
