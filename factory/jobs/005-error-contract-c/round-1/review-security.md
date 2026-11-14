VERDICT: PASS

Reviewed b57e6dc against a9bc904 (src/api/endpoints.py; tests read only for coverage). PoCs were run from a `git archive` copy in /tmp/claude-501/sec-c (verified `src` resolves to the copy). The PoC scripts are in /tmp/claude-501/sec-c-poc. No blocking findings.

1. Information exposure: PASS.
   - Hostile upstream 401 on a local server. Its message echoed the `Authorization` header (the pool key) plus `/etc/passwd` and a fake traceback.
     - The key came back as `Bearer [redacted]` on both stream and non-stream. A's redaction covers the pool.
     - Upstream-supplied text such as `/etc/passwd` is passed through as the message by design, so it is not a proxy leak.
     - The `Server` and `Set-Cookie` upstream headers were dropped.
   - Conversion bug: `convert_claude_to_openai` raising `ValueError("boom /Users/x/secret <key>")` gives 500 with the body `Internal server error` and no extra headers. The text and the key appear only in the server log traceback (endpoints.py:~284-286), never in the response.
   - The 499 `_ClientGone` body is the static `Client disconnected`.
   - The generic HTTPException branch (endpoints.py:278-282) echoes `e.detail` and `e.headers`. In `/v1/messages` the only sources are the static 499 messages in endpoints.py and client.py, and the converter's static "No choices in OpenAI response". Nothing exception-derived reaches it.

2. Forwarded headers: PASS.
   - With an upstream sending Request-Id with a control byte, X-Request-Id, Retry-After, x-should-retry, Anthropic-Ratelimit-Unified-Status, Set-Cookie and Server, only x-request-id, retry-after, x-should-retry and the unified-ratelimit header were forwarded. The invalid Request-Id was dropped. This is A's whitelist; C adds no headers except the own-429 `Retry-After`.
   - The own 429 `Retry-After` is `max(1, min(60, int(...)))` and an integer string (endpoints.py:~128). An upstream 429 without the header gets none.
   - Upstream `retry-after` is uncapped by design (digits only, at most 10 digits).

3. First-chunk priming: PASS.
   - I ran a real uvicorn server against a raw asyncio upstream, with 100 concurrent streams per run and the client giving up after 2 s. One upstream accepted and never answered. The other sent SSE headers and then trickled keep-alives.
     - Result: `active_requests` was empty on every client, and `/health` answered in about 3 ms while the streams hung.
     - All 100 upstream sockets were closed by the proxy (`closed handlers 100` out of 101 connections; the 101st was the health probe or the extra listener). The task count returned to 6, the baseline.
     - I first got 0 closed in silent mode, but that was my fake upstream sleeping instead of reading EOF. Changing it to `await r.read()` confirmed the proxy closes the connection.
   - `CancelledError` is not swallowed. The `except BaseException` block cleans up and re-raises. `create_message` does not catch it.
   - A `_prepend` generator that is never started or only partly consumed could skip its `finally`. The response converter owns that path, which is in D's scope, and I saw no leak in the PoC.

4. Unauthenticated surface: PASS.
   - With `ANTHROPIC_API_KEY` set, missing and wrong keys both return 401 `{"detail":"Invalid API key. Please provide a valid Anthropic API key."}`. This is unchanged and identical for the two cases.
   - 422 keeps FastAPI's `detail` list.
   - No new routes. The diff changes only create_message and its helpers.
   - Error bodies on `/v1/messages` never mention whether a client key is configured. The only config-dependent message is the own 429 `All API keys exhausted...`, which is unchanged in substance.

5. Log lines: PASS.
   - The new lines in endpoints.py log only the first 8 chars of the request id, the status and the error type. They are `%s`-formatted, so there is no f-string injection. They contain no upstream text.
   - The generic-500 handler logs a traceback (server-side only, as designed). A conversion error whose message embeds a secret would land in the log. That is the previous behaviour and is not a regression.
   - The client's own log line (`Model error ... Error code: 401 ...`) is redacted and truncated.

Non-blocking notes (no change required):
- The hang bound relies on the SDK's per-phase `REQUEST_TIMEOUT`. An upstream that sends headers and then trickles keep-alive comments resets the read timeout, so it can hold a worker until the client disconnects. Disconnect cleanup is verified above. The upstream is operator-configured, not attacker-controlled, so this is low severity.
- endpoints.py:325 (`count_tokens`: `detail=str(e)`) still leaks exception text. It is pre-existing, outside this slice and not on `/v1/messages`. It is worth a follow-up.
