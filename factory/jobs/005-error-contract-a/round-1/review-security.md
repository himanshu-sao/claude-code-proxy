VERDICT: CHANGES

Reviewed 24d713c (src/core/errors.py, src/core/client.py, tests/test_errors.py) against 67de01a. I ran PoCs in a scratch copy under /tmp/claude-501/sec-a/. The main checkout was untouched.

## Findings

1. MEDIUM: upstream-controlled non-ASCII header values crash the error response (src/core/errors.py:36, 120-123).
   - `_INTEGER_RE = ^\d+$` is Unicode-aware, so it accepts non-ASCII digits. `x-request-id`, `request-id`, `x-should-retry` and `anthropic-ratelimit-unified-*` are forwarded with no character or length check.
   - Reproduction: build an `APIStatusError` whose response carries `retry-after: ٣` (Arabic-indic digit, UTF-8 bytes) or `x-request-id: r€`. `map_upstream_error` returns those values in `.headers`. `UpstreamHTTPError(mapped)` raised from a FastAPI route then gives a plain `500 Internal Server Error` with `text/plain`. Starlette encodes headers as latin-1 and fails. The client loses the real status and message, and a traceback is logged.
   - A misbehaving or hostile upstream can trigger this at will. Impact is a lost error contract, not code execution.
   - Fix:
     - Use `re.fullmatch(r"[0-9]{1,10}", v, re.ASCII)`.
     - For the other forwarded headers, drop values that are not printable ASCII (`[\x20-\x7e]*`) and cap them at roughly 256 characters.
     - Also use `fullmatch` rather than `match` with `$`. `$` accepts a trailing newline (`"5\n"` matches), though `.strip()` happens to neutralise that today.
   - CR/LF injection is not reachable: h11 and httpx reject or split those bytes before they reach us. The charset check above makes this explicit. Add a test.

2. LOW: the original exception, with its unredacted text, is chained and reaches logs through the converter (src/core/client.py:128 and 181, `raise ... from e`).
   - On the stream path, `UpstreamError` propagates into `response_converter`'s generic `except Exception`. That handler runs `logger.error(traceback.format_exc())` (response_converter.py lines ~201 and ~385). `format_exc` prints the `__cause__` chain, so the raw upstream `APIStatusError` text is logged with no redaction. That text can include a key echo such as "Incorrect API key provided ...".
   - The client-visible text is safe. `safe_error_summary` gives only `UpstreamError`.
   - Fix, either of:
     - Raise `from None` after logging the redacted text.
     - Build the `UpstreamError` so its `__cause__` is not the raw SDK error. Keep the type and status in `.mapped`.
   - The converter and endpoints are out of scope for this slice, so `from None` in client.py is the in-scope fix. Redaction in errors.py is unaffected.

3. LOW: log forging through the client.py warning (client.py:208-216).
   - `_redact(str(error_detail))[:100]` is logged with `%s`. Upstream text may contain `\n`, so a forged log line can be injected (`...\n2026-.. | ERROR | ...`). Escape it, for example with `repr()` or `.replace("\n", "\\n")`. Redaction happens before truncation, so a key split by the 100-character cut is not a problem.

4. INFO: what redaction covers (errors.py:142-143, client.py:196-197).
   - Covered: every exact, case-sensitive occurrence of the client's own `self.api_key`. This includes `Bearer <key>` and `Authorization:` echoes, and keys containing regex-special characters, because `str.replace` is literal. Redaction applies to the `message` field and to the log line. `repr`, `str` and `args` of `UpstreamHTTPError` and `UpstreamError` contain only the redacted message plus `MappedError`, which also holds the redacted message. I confirmed this with a PoC.
   - Not covered, confirmed by PoC:
     - Masked or partial keys (`KEYV***2345`).
     - Different-case keys.
     - Base64, URL-encoded (`%31`) and whitespace-split forms.
     - Other keys in the `OPENAI_API_KEY` round-robin pool. Only the failing client's key is redacted. An upstream that echoes a different pool key is not scrubbed. Redacting `config.providers[*].api_key` would close this at small cost.
     - The proxy's own `ANTHROPIC_API_KEY`. This is unlikely to reach the upstream.
   - A very short key (the PoC used the 1-character key `a`) mangles every occurrence of that character in the text (`b[redacted]n[redacted]n[redacted]`). This is not a leak. Consider a minimum length, for example 8, below which redaction is skipped. Real keys are longer, so this is a nit.
   - All of these are best effort. Treat the exact-match redaction as defence in depth, not a guarantee.

5. Checked and clean.
   - `json.dumps` is the only JSON builder. The `data: {{` f-string lines are gone from client.py. `error_json` round-trips hostile text.
   - The `Streaming error:` text uses `safe_error_summary` (type and status only), so the key cannot reach the client through `str` or `repr` of these exceptions.
   - `detail` is JSON-encoded by FastAPI.
   - No new dependencies. errors.py imports only the stdlib, fastapi and `openai._exceptions`.
   - No SSRF or config surface changed.
   - The `Upstream error (HTTP n)` fallback is safe.
   - Pre-existing and out of scope: endpoints.py logs `f"... {e}"` on non-HTTPException paths.
