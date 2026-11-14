# Factory Backlog

Features queued for `/factory next`. One per line, checked off when run.

- [x] Add a `/v1/models` cache TTL so model discovery doesn't hit upstream on every request
- [ ] Health-check endpoint reports per-key RPM and cooldown status
- [ ] Optional per-request token-usage logging (env-var gated) for cost tracking
- [ ] Pass-through mode: forward desktop-app connector/plugin/org endpoints to api.anthropic.com instead of stubbing them (no restrictions on connectors; needs user's real Anthropic auth to work)

## Follow-ups from job 005 (error contract). Sources: factory/jobs/005-error-contract/whole-review.md, whole-api.md and the decision.md files of slices a-e

- [ ] HIGH, gating: verify with the real upstream that every configured tier and fallback model sends a non-null `finish_reason` on normal streamed replies (text, tool call, max_tokens cut, reasoning). A stream without one is now an error; if a model omits it, add a per-model opt-out. Not yet verified.
- [ ] Observe how the real Claude Code CLI displays the new errors (400 before the stream, 429/503 retries, mid-stream `event: error`, the `capability_rejected: prompt_too_long` prefix). Unverified. See live-claude-code.md if it exists.
- [ ] MEDIUM-LOW: no total deadline for the first stream chunk; an upstream that only sends keep-alives can hold a worker until the client disconnects (`REQUEST_TIMEOUT` is per phase).
- [ ] LOW: `count_tokens` and `/test-connection` put `str(e)` in the error detail (existing leak of exception text; outside the Anthropic envelope).
- [ ] LOW: the client warning log writes raw upstream text: escape ESC and U+2028, and make it safe for lone surrogates (they print a `--- Logging error ---` block).
- [ ] LOW: the converter's catch-all logs `traceback.format_exc()`, which can include a chained cause with unredacted text.
- [ ] LOW: `map_upstream_error` calls `str(exc)` several times unguarded; compute it once inside a try. The `Unexpected error: <TypeName>` fallback does not sanitise a custom class name.
- [ ] LOW: a `finish_reason` on a non-first choice counts as a finish, but the converter reads only `choices[0]`.
- [ ] LOW: the SDK stream object is not explicitly closed on client disconnect or cancel.
- [ ] LOW: tests: the disconnect tests would pass without `cancel_request` and the `active_requests` pop; no assertion that the first chunk appears exactly once; no HTTP-level test for the 499 envelope; no end-to-end TestClient test for a mid-stream failure through `endpoints.py`.
- [ ] CLEANUP: dead code `convert_openai_streaming_to_claude` in `response_converter.py`; unused `MappedError.retryable` and `counts_as_model_failure` fields; the `_empty()` branch in `endpoints.py` is unreachable with the real client.
- [ ] DOCS: a README/QUICKSTART troubleshooting line for the "Upstream stream ended before a finish_reason was received" error.
- [ ] Earlier audit backlog (not done): converter crashes P5-P8 (tool_choice none, text blocks beside tool_result, missing tool_result content, server tools without input_schema), P12, P14, P16, P19 (`testpaths`), P20 (undocumented env vars).
