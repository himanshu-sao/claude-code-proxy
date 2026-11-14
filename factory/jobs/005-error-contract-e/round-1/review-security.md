VERDICT: PASS

I reviewed `git diff 1cff272 factory/005-error-contract-e`. I ran PoCs against a `git archive` copy in /tmp/claude-501/sec-e/tree, and `src` resolved to that copy. The scratch suite gave 592 passed (`OPENAI_API_KEY=test-key`, `-p no:cacheprovider`, `--ignore=tests/test_main.py`). The PoC scripts are /tmp/claude-501/sec-e/poc/poc1.py and poc2.py. I found no blocking or medium issues. The notes below are low or informational.

## 1. Lone-surrogate sanitising (src/core/errors.py:40, 178-180) - OK
- I fed the mapper APIStatusError (message taken from the body, and from the plain message) and a plain RuntimeError. The texts were a lone U+D800, a valid astral emoji, a literal surrogate pair (`😀`), mixed valid and lone surrogates, empty text, and 200k lone surrogates plus 1000 emoji.
  - `error_json(...).encode("utf-8")` and `message.encode("utf-8")` succeeded in all 18 combinations.
  - A valid astral character (U+1F600) came through unchanged.
  - A literal surrogate pair in a Python str is two lone surrogates, so it becomes two U+FFFD. That is correct, and no valid text is corrupted.
- Redaction runs before sanitising. Sanitising only swaps characters for U+FFFD, so it cannot create or hide a key occurrence.
  - Surrogate or U+FFFD characters inserted into a key stop it matching. The text then no longer contains the key, so nothing leaks.
  - A key preceded by a surrogate was still redacted (`'x [redacted] y'`).
  - Redaction is exact-substring only, which is the same as before this diff.
- Header values are not affected by sanitising, but they are already safe (errors.py:134-150). `_SAFE_HEADER_RE` only accepts printable ASCII, and retry-after must be digits. I ran a fake response with surrogate, non-ASCII and `\n` values in request-id, x-request-id, retry-after and the anthropic-ratelimit-unified-* headers. All were dropped (`{}`), so every forwarded header is latin-1 and UTF-8 encodable.
- Low (not new, not blocking): `str(exc)` is still called unguarded in the mapper. An exception whose `__str__` raises propagates out of `map_upstream_error`. The SDK does not produce such exceptions. This is pre-existing.

## 2. Truncated-stream error (src/core/client.py:169-189, 215-219; errors.py:69-78) - OK
- `TRUNCATED_STREAM_MESSAGE` is a constant. It carries no upstream text, key or URL. Headers are `{}`. The log line uses the same constant, so it is injection-free.
  - In the PoC the message contained neither the key nor the upstream host.
- The result is 502 `api_error`, retryable true, not a model failure. The log shows `model_error=False`, once per truncation.
- Paths I ran, with `active_requests == {}` at the end in every case:
  - text then clean close, zero chunks, and a usage-only final chunk: all raise UpstreamError, with no `[DONE]` and no success report.
  - stop, and stop plus a trailing usage chunk: `[DONE]` is last and success is reported.
  - an exception inside the async-for: mapped, with the key redacted.
  - an empty-message ConnectionResetError: gives `Unexpected error: ConnectionResetError`.
  - client disconnect (`aclose` after the first chunk), the `cancel_request` flag, and task cancellation: all clean up `active_requests` in the `finally`. The cancel flag path returns quietly, with a 499 log.
- Info (pre-existing, not in this diff): on disconnect or cancel the SDK stream object is not explicitly closed in the generator. My stub stream showed `closed=False` until it was garbage-collected. The new early raise does not worsen this, because the iterator is already exhausted at that point.
- Info: the new raise sits inside the `try` and `except UpstreamError: raise` passes it through. There is no double accounting and no double wrapping.

## 3. Empty-text fallback (src/core/errors.py:167) - OK
- It uses `type(exc).__name__` only, never a repr or attributes. A class whose `__repr__` returns "SECRET" and whose `__str__` is empty gave `Unexpected error: Weird`. A whitespace-only message also falls back to the type name.
- Low: the type name is the proxy's own Python class name, so it discloses nothing sensitive. It names an internal exception class to the client. That is a trivial disclosure and it is what the user asked for.
- Info (pre-existing): the client warning log at client.py:243 passes `str(error_detail)` containing `\ud800` to the logging handlers. A strict UTF-8 file or stream handler could raise inside `logging`, and logging swallows that via `handleError`. It is not a request failure. The `\r\n` escaping and key redaction in that log line work.

## 4. README (README.md:21) - OK
- The sentence is limited to what the proxy does: the real HTTP status, the Anthropic error shape, and a failing stream ending with one `event: error` and no `message_stop`. It makes no claim about Claude Code and none about security. It is not misleading.

## Other checks
- No new dependencies. No config or auth changes. No key-like literals added.
- The `finished` flag logic reads `c.get("finish_reason")` on dicts from `model_dump()`, so odd upstream chunk shapes cannot raise anything beyond what already happened.
