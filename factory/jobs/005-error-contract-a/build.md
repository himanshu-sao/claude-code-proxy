GREEN

# Build: 005-error-contract-a (shared error mapping + client refactor)

Branch: `factory/005-error-contract-a` (worktree `.claude/worktrees/005-a`)
Commits: `24d713c` feat: shared upstream error mapping for OpenAIClient (originally d088a8f, trailer amended by coordinator); `3b84a81` fix: harden forwarded headers, redaction and logging (round 1 rework)
Files changed (only the three allowed): `src/core/errors.py` (new), `src/core/client.py`, `tests/test_errors.py` (new).
Not touched: `src/api/endpoints.py`, `src/conversion/response_converter.py`, `src/core/config.py`, docs, existing tests, `.env`, `logs/`, `model_contexts_cache.json`, the main checkout, port 8082.

## What changed

- `src/core/errors.py` (new, stdlib + fastapi + `openai._exceptions` only; no `src.core.config` import):
  - `MappedError` NamedTuple (status, error_type, message, headers, retryable, counts_as_model_failure).
  - `map_upstream_error(exc, api_key=None)`: status from `status_code` (401/429 fallback for the SDK classes, else 500); type table from the spec, other 4xx invalid_request_error, other 5xx api_error; message from `body["error"]["message"]` then `body["message"]` then `exc.message` then `str(exc)`, with the `Upstream error (HTTP n)` fallback for blank text; key redaction to `[redacted]`; `capability_rejected: prompt_too_long ` prefix on 400/413 for the five triggers or `code == "context_length_exceeded"`; forwarded headers (lowercase; integer-only `retry-after`; `x-should-retry`, `request-id`, `x-request-id`, `anthropic-ratelimit-unified-*`); `retryable` honours `x-should-retry` else 408/409/429/5xx.
  - `counts_as_model_failure(status, text)`: the existing `_report_model_error` rule moved here unchanged.
  - `error_envelope`, `error_json` (json.dumps), `UpstreamError` (plain Exception, `.mapped`), `UpstreamHTTPError(UpstreamError, HTTPException)` with `status_code`, `detail`, `headers=mapped.headers or None`.
- `src/core/client.py`:
  - Non-stream: 499 cancellation `HTTPException` kept; every other failure raises `UpstreamHTTPError`.
  - Stream: no more yielded error lines. Cancellation reports 499 and returns without yielding. Other failures raise `UpstreamError`. The f-string JSON is gone.
  - `_handle_upstream_exception` maps the error, calls `_report_model_error` once, and calls `config.report_rate_limit` for RateLimitError.
  - `_report_model_error` keeps its signature and delegates to `counts_as_model_failure`. Its log line now shows the redacted text.
  - `classify_openai_error` deleted (no callers left in src or tests).

## Test design

`tests/test_errors.py` has 70 new offline tests:
- Mapping table for 400, 401, 403, 404, 413, 422, 429, 500, 502, 503, 529, plus a 6-tuple unpack check.
- Message source precedence, empty-message fallback, missing `status_code` defaults, non-APIError to 500, unknown 4xx/5xx.
- Header forwarding and dropping, retry-after cases (integer, HTTP-date, `abc`, `-5`, `1.5`, empty).
- `x-should-retry` and `retryable` rules.
- Redaction (edge 14).
- Prompt-too-long prefix for all five triggers at 400 and 413, the `code` trigger, and no-prefix cases (plain 400, 503, 401).
- `error_json` round-trip with quotes, backslashes, newlines and a fake SSE line; no f-string JSON in client; `classify_openai_error` absent.
- Import of `src.core.errors` with an empty environment and no `src.core.config` in `sys.modules` (subprocess).
- `counts_as_model_failure` for 429, 503, the text triggers, and plain 400/401.
- Client integration: once-per-call reporting for 503/400/401 on both paths; `UpstreamHTTPError` status/detail/headers; `UpstreamError` on the stream path with `.mapped`; Azure path (`api_version`) gives identical mapping; unexpected exception to 500; key redaction in a client error; real `Config` (`BIG_MODEL="a,b"`, threshold 3) switches to `b` after three 503s and reports the fourth against `b`, on both paths.

No existing test was edited, and none needed to change.

## Commands and results

Venv check (run from the worktree):
```
/Users/himanshusao/Work/src/extra/himanshu-sao/claude-code-proxy/.venv/bin/python -c "import src,os; print(os.path.realpath(os.path.dirname(src.__file__)))"
→ /Users/himanshusao/Work/src/extra/himanshu-sao/claude-code-proxy/.claude/worktrees/005-a/src
```

Offline gate (before and after the format pass, same result):
```
OPENAI_API_KEY=test-key .venv/bin/python -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider -q
→ 447 passed, 4 xfailed, 40 warnings in 6.32s
```
447 = 377 baseline + 70 new. Baseline was re-measured in the worktree before my edits: 377 passed, 4 xfailed.

New tests alone:
```
OPENAI_API_KEY=test-key .venv/bin/python -m pytest tests/test_errors.py -p no:cacheprovider -q
→ 70 passed in 0.77s
```

Format:
```
.venv/bin/python -m black -l 100 src/ tests/     (reformatted my files only)
.venv/bin/python -m black --check src/ tests/    → 31 files would be left unchanged.
.venv/bin/python -m isort src/ tests/ ; isort --check-only → ISORT_OK
```

Format pass was run before the offline gate result above; the gate was re-run afterwards and is unchanged at 447 passed, 4 xfailed.

Key and JSON scans:
- `grep -nE "(sk-|ghp_)[A-Za-z0-9]"` over `errors.py`, `client.py`, `test_errors.py`: no matches.
- `grep -n "data: {{" src/core/client.py`: no matches.
- The pre-commit secrets hook passed on commit: "commit scanned, no secrets found."

## xfail status

Strict xfails explicitly run:
```
OPENAI_API_KEY=test-key .venv/bin/python -m pytest "tests/test_job003_endpoints.py::test_stream_upstream_error_is_visible_to_client" -p no:cacheprovider -q -rxX
→ XFAIL [400], [422], [503], [429] (all four)
→ 4 xfailed
```
None of them XPASS. They are still xfailed because the upstream text is not exposed in the stream body until slice D. The stream still returns HTTP 200 with the converter's `event: error` ("Streaming error: UpstreamError"), which does not contain the upstream text. The endpoint and converter are unchanged, as the spec requires.

## Mutation checks

Scratch copy at `/tmp/claude-501/mut`, with `/tmp/claude-501/mutate.py` applying one edit at a time. The tests were run as `tests/test_errors.py`, with the file restored after each mutation. Results:

| # | Mutation | Result |
|---|----------|--------|
| M1 | Empty `PROMPT_TOO_LONG_PREFIX` (remove prefix) | 13 failed |
| M2 | Redaction made a no-op | 2 failed |
| M3 | `error_json` replaced with f-string JSON | 1 failed |
| M4 | f-string `data: {"error"...}` stream line restored in client | 1 failed |
| M5 | Forward any `retry-after` (HTTP-date and `abc` kept) | 5 failed |
| M6 | 400 counted as model failure | 3 failed |
| M7 | Drop the `context window` trigger | 4 failed |
| M8 | Stream path raises `UpstreamHTTPError` instead of `UpstreamError` | 2 failed |
| M9 | Model failure reported twice per call | 4 failed |
| M10 | Mapped status forced to 500 | 18 failed |

All mutations ran on the scratch copy. The worktree was not mutated: each mutated file was restored from the committed version before the next run. The scratch copy under /tmp/claude-501/mut was left in place.

## Acceptance criteria

1. Mapping table, fallback message, forwarded headers, redaction: covered and passing.
2. Prompt-too-long prefix: five triggers at 400 and 413, `code` trigger, and no-prefix cases. Passing.
3. G5 round-trip: passing. `client.py` contains no `data: {{`.
4. G11 and edge 11: non-stream and stream reporting counts (503 = 1, 400 = 0, 401 = 0). Real `Config` fallback switches to `b` after three 503s. `counts_as_model_failure` truth table. Passing.
5. Client exposure: `UpstreamHTTPError` is an HTTPException with matching status/detail/headers; the stream raises `UpstreamError` (not HTTPException) with `.mapped`; Azure path identical; import works with no env. Passing.

## Notes and things not verified

- Commit trailer: the task specified `Co-Authored-By: Claude Code <noreply@anthropic.com>`, while the harness attribution reminder specified `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. The commit uses the Sonnet 5.5 line. Change it if you want the Claude Code line.
- Location of this file: the job folder `factory/jobs/005-error-contract-a/` exists only in the main checkout (it is untracked and not in the worktree). I wrote `build.md` there because that is where spec.md lives. I did not write anything else in the main checkout.
- Not run: live verification against a real upstream or a running proxy on any port (out of scope for this slice and forbidden for this builder).
- Known behaviour left for slice C/D: the stream path's error text is still masked as the converter's "Streaming error: UpstreamError(...)" string, and the endpoint still returns `{"detail": ...}` on non-stream errors. Both are replaced by slices C and D.
- The `uv run` form was not used. All runs used the absolute shared venv interpreter.


# Round 1 rework (commit `3b84a81`)

Files: `src/core/errors.py`, `src/core/client.py`, `tests/test_errors.py`, plus the one docstring line in `src/core/logging.py`. Trailer: `Co-Authored-By: Claude Code <noreply@anthropic.com>`.

| # | Item | Fix | Covering tests (tests/test_errors.py) |
|---|------|-----|------|
| 1 | security 1 (MEDIUM) header safety | `retry-after` must `fullmatch [0-9]{1,10}` (re.ASCII) after strip. Other forwarded headers dropped unless printable ASCII 0x20-0x7e and at most 256 chars. | `test_retry_after_strict_ascii_digits`, `test_retry_after_surrounding_whitespace_stripped`, `test_retry_after_ten_digits_kept`, `test_unsafe_forwarded_header_values_dropped`, `test_unsafe_ratelimit_header_dropped_and_boundary_kept`, `test_non_ascii_headers_do_not_break_real_fastapi_response` (tiny FastAPI app + TestClient; non-ASCII retry-after and x-request-id give real 429, `{"detail": "slow down"}`, safe `request-id` forwarded) |
| 2 | security 2 (LOW) chaining | Both mapped raises use `from None`. | `test_mapped_errors_do_not_chain_raw_exception` (stream and non-stream: `__cause__ is None`, `__suppress_context__ is True`) |
| 3 | security 3 (LOW) log forging | Warning log text has CR and LF escaped to `\r` and `\n`. | `test_log_line_escapes_newlines` (caplog: one record, no raw newline) |
| 4 | security 4 (INFO) pool redaction | New `redact_keys` and `extra_keys` param in errors.py (no config import). `client._pool_keys()` reads `config.providers` lazily and defensively; keys under 8 chars skipped. Also applied to the log line. | `test_redact_keys_pool_and_min_length`, `test_client_redacts_whole_provider_pool`, `test_pool_read_is_defensive`; `test_errors_module_imports_without_env_or_config` still passes |
| 5 | code LOW stale docstring | `safe_error_summary` docstring now names `src.core.errors.map_upstream_error`. | n/a |
| 6 | code LOW cancel tests | Added tests; see below. | `test_stream_cancel_reports_499_once_and_yields_nothing_more`, `test_non_stream_asyncio_cancellation_propagates_and_cleans_up`, `test_non_stream_cancel_request_gives_499` |

Extra behaviour change (found while writing item 6): when the non-stream caller was cancelled with `asyncio.CancelledError`, the inner completion and cancel-wait tasks were left running ("Task was destroyed but it is pending"). `create_chat_completion` now cancels both on `CancelledError` and re-raises. The new cancellation test covers it, and the warning is gone.

Behaviour notes:
- `retry-after` with surrounding whitespace (for example `" 5\n"`) is still accepted after `.strip()` and forwarded as `5`. Internal whitespace, signs, non-ASCII digits and more than 10 digits are dropped.
- Redaction skips keys under 8 chars, so a short configured key is not redacted (by request).

## Rework results (real runs, worktree venv, from the worktree)

- Venv check: src resolves to `.../claude-code-proxy/.claude/worktrees/005-a/src`.
- Offline gate `tests/ --ignore=tests/test_main.py`: **481 passed, 4 xfailed** (was 447 passed, 4 xfailed; +34 new tests).
- `tests/test_errors.py` alone: 104 passed.
- Strict xfails `test_stream_upstream_error_is_visible_to_client[400|422|503|429]`: still 4 XFAIL, 0 XPASS ("4 xfailed").
- `black --check -l 100 src/ tests/`: 31 files unchanged. `isort --check-only`: OK. No lines over 100 chars. Key-literal grep clean; pre-commit secrets hook passed.

## Mutation checks (scratch copy `/tmp/claude-501/mut2`, one edit at a time, `tests/test_errors.py`)

| # | Mutation | Result |
|---|----------|--------|
| R1 | retry-after regex back to Unicode `\d+` | 5 failed |
| R2 | retry-after length cap removed (`[0-9]+`) | 1 failed |
| R3 | charset check removed for other headers | 14 failed |
| R4 | length cap removed for other headers | 3 failed |
| R5 | charset widened to `\x00-\x7f` | 6 failed |
| R6 | min key length removed | 2 failed |
| R7 | client stops passing pool keys | 1 failed |
| R8 | pool read not defensive | 1 failed |
| R9 | `extra_keys` ignored in `map_upstream_error` | 2 failed |
| R10 | `from e` restored on non-stream | 1 failed |
| R11 | newline escaping removed from log line | 1 failed |
| R12 | stream cancel yields a line again | 1 failed |

Not mutation-checked: the `CancelledError` cleanup block in `create_chat_completion` (verified only by the absence of the "Task was destroyed" log output when running the cancel tests, not by a failing mutation).
