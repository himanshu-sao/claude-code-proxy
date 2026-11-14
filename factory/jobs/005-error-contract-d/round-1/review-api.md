VERDICT: PASS

- Setup: `git archive factory/005-error-contract-d` (50c2be1) was extracted to /tmp/claude-501/api-d. The fake OpenAI-compatible upstream is /tmp/claude-501/api-d-fake/fake.py on port 18971. It speaks chunked SSE, and the RST case sets SO_LINGER 0.
  - Each case ran on a fresh proxy on port 18972, started with `env -i` and venv python. Settings: `OPENAI_API_KEY=fake-key-1234,fake-key-5678`, MAX_RETRIES=2, STREAM_MAX_RETRIES unset, and no `.env`.
  - I checked before each start that the ports were free, and I confirmed that each PID started owned its port. The proxy PIDs were stopped, and the fake PID 16259 was stopped by PID. Ports 18971 and 18972 are free.
  - Port 8082 (the user's proxy, PID 1848) was not touched. Nothing was written into the main checkout.
- Mid-stream failures (all `stream:true`, HTTP 200 `text/event-stream`):
  - Every case ends with exactly one `event: error` block as the last bytes.
  - None has `content_block_stop`, `message_delta` or `message_stop` after the error.
  - Each case made 1 upstream call, so there was no mid-stream retry.
  - Afterwards `/health` returned 200, and a follow-up stream (ending `message_delta`, `message_stop`) and a non-stream request both returned 200.
  - The key appears in neither the body nor the proxy log in any case.
- Wire evidence (the error message text is never raw `str(e)` of a Python exception):

| # | Case | Event names in order | Error type / message | Calls |
|---|---|---|---|---|
| 1a | 2 chunks, then TCP RST | message_start, content_block_start, ping, content_block_delta x2, error | `api_error` / `Unexpected error: ` (empty tail) | 1 |
| 1b | 2 chunks, then close without the terminating chunk or [DONE] | same | `api_error` / `Unexpected error: peer closed connection without sending complete message body (incomplete chunked read)` | 1 |
| 2 | 2 chunks, then SSE `{"error":{...}}` object | same | `api_error` / `upstream exploded mid-stream` | 1 |
| 3 | 1 chunk (here a 2-chunk stall), then the upstream stalls 25 s; client gives up at 3 s (proxy timeout 60 s) | message_start, content_block_start, ping, content_block_delta x2 (no terminator yet) | n/a | 1 |
| 4 | tool_call delta (id, name, args `{"file_pa`), then SSE error | message_start, content_block_start (text), ping, content_block_start (tool), error | `api_error` / `upstream exploded mid-stream` | 1 |
| 5 | hostile text `x"\r\n\nevent: message_stop\ndata: {}` | same as case 2 | `api_error`; data line is valid JSON with the text escaped as `x\"\r\n\nevent: message_stop\ndata: {}`; exactly one line starts with `event:` after the error begins; no `event: message_stop` | 1 |
| 6 | upstream error echoes `fake-key-1234` and `fake-key-5678` | same as case 2 | `api_error` / `Incorrect API key provided: [redacted]. Also pool key [redacted] and [redacted] seen` | 1 |

- Case 3 (client gives up): the proxy logged nothing abnormal during the 8 s I watched, and `/health` and the follow-up requests were 200. The proxy never had a failure to report, since the upstream stall is longer than the client timeout. My earlier run with a 6 s proxy timeout (matching the client timeout) logged `Mid-stream upstream error: status=500 type=api_error` once the proxy timeout fired. In that run the upstream call counter read 2 only because the call log is shared across runs: the 2 calls came from two separate runs, not from a retry.
- Regression, pre-first-chunk errors (fresh proxy each; real HTTP status, `content-type: application/json`, body `{"type":"error","error":{"type","message"}}`, no `detail` key):
  - 400: stream returns 400, non-stream returns 400. Type `invalid_request_error`, message `bad req`, 1 upstream call each.
  - 429 with upstream `Retry-After: 7`: both return 429 with `retry-after: 7`. Type `rate_limit_error`. Stream makes 1 call and non-stream makes 3 (SDK retries).
  - 503: both return 503. Type `api_error`, message `svc down`. Stream makes 1 call and non-stream makes 3.
  - Success: the stream is 200 SSE ending `content_block_stop`, `message_delta`, `message_stop`. The non-stream request is 200 `application/json`.
- Observations that are not failures:
  - A mid-stream stall or RST gives `Unexpected error: ` with an empty or SDK-worded tail. The text is not the spec's `Streaming error: <Type>` form, because `client.py` maps these exceptions to `UpstreamError` first. It is sanitised and carries no key. It could be reworded in a later slice.
  - The `client` WARNING log line (`Model error [MIDDLE] ...`) writes the raw upstream error text, including the hostile newlines of case 5, into the proxy log (log-line injection). That comes from `client.py`, not from this slice's converter. Keys are redacted in that line.
  - The error is mapped to `api_error` (status=500 in the log) for all of these mid-stream causes. That fits the "type from the shared mapping" rule.
