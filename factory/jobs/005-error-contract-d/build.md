# Build 005-error-contract-d: GREEN

Branch `factory/005-error-contract-d`, cut from 6c82d50. Commit hash: see `git log -1` on the branch (also in the handback).
This file is untracked in the worktree (the factory job folders are untracked); it is not part of the commit.

## What changed
- `src/conversion/response_converter.py` (only `convert_openai_streaming_to_claude_with_cancellation`):
  - New `except UpstreamError` placed BEFORE `except HTTPException` (UpstreamHTTPError is both). Logs status and type only, yields one `event: error` built by `error_json(e.mapped.error_type, e.mapped.message)`, returns. No `content_block_stop`, `message_delta` or `message_stop`; no second accounting.
  - Generic `except Exception`: log lines kept, client event is now `error_json("api_error", "Streaming error: <TypeName>")`; raw exception text never reaches the client.
  - 499 cancelled path unchanged. Legacy `convert_openai_streaming_to_claude`, endpoints.py, errors.py untouched.
- `tests/test_midstream_errors.py` (new, 10 tests): 503/429/400 mid-stream, generic exception sanitised, 499 still `cancelled`, hostile text, tool-call-started edge 6 (decision in docstring), `[DONE]` without finish_reason, stream ending without `[DONE]`, byte-identical success path.
- `QUICKSTART.md`: new "## Errors" section before "Verify your setup". Stale test counts there left alone. README unchanged.
- The four xfail markers were not touched (already gone from slice C).

## Baseline bytes capture
Before editing the converter, ran /tmp/claude-501/cap/capture.py (outside the repo) against the UNMODIFIED converter at 6c82d50 (HEAD 6c82d50, tree clean of source changes), `uuid.uuid4` patched to a fixed UUID. Fixture: text deltas incl. non-ASCII and a blank line, one tool call with args split across two chunks, finish_reason tool_calls, usage chunk with cached_tokens, `[DONE]`. Output stored verbatim as the `BASELINE_SUCCESS_OUTPUT` literal. Caveat caught: my first capture ran with the script directory on sys.path and imported `src` from the MAIN checkout; I discarded it and recaptured with PYTHONPATH set to the worktree plus an assert on `src.__file__`. The test uses the same fixture and passes against the modified converter.

## Commands and results
- `.venv/bin/python -c "import src,os; ..."` run from the worktree printed the worktree's src.
- `OPENAI_API_KEY=test-key .venv/bin/python -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider`: 570 passed (560 baseline + 10 new), 0 failed, 0 xfailed, 0 XPASS.
- black (line length 100) and isort (profile black, 100) on src/ and tests/: `--check` clean. Key-literal grep: only a pre-existing `sk-your-key` placeholder in QUICKSTART.md; none added.

## Acceptance criteria
1 (G4), 2 (G6), 3 (edge 6), 4 (edge 7), 5 (G12): all pass.

## Mutation checks (scratch copy under /tmp/claude-501/mut)
- (a) message_stop emitted after the error event: 5 failed (3 parametrized last-event tests, hostile text, tool-call edge 6).
- (b) raw `str(e)` in the generic handler: 1 failed (`test_midstream_generic_exception_is_sanitised`; message became `Streaming error: secret key-abc`). My first attempt at this mutation was a malformed edit that ran nothing; redone correctly.
- (c) UpstreamError branch dropped (falls to generic): 4 failed (3 parametrized + hostile text).

## Not verified
- Live Claude Code behaviour: whether it shows the error message, retries, or treats a body without `message_stop` as expected. Not checked here.
- No end-to-end run through endpoints.py with a real upstream; the converter is driven directly.
- tests/test_main.py (needs a live proxy) not run.

## Round 1 rework (GREEN) - commit 1e99bd1 (new commit on top of 50c2be1)
Reviewer CHANGES (code review) addressed, QUICKSTART.md and tests/test_midstream_errors.py only; src/ untouched.
1. Bullet 2: removed the unverified "Claude Code retries on its own" claim. It now says the HTTP status is already 200 (headers sent), the stream ends with one `event: error` and no `message_stop`, and that how Claude Code displays it has not been checked in a live session.
2. Bullet 1: scoped to upstream errors and the proxy's own 429 (all keys exhausted) before the first byte; removed "auth"; states that an invalid proxy API key (401) and an invalid request body (422) keep the `{"detail": ...}` shape.
3. Optional tests added: `test_midstream_499_still_cancelled_event` now also asserts the cancelled event is last, appears once, and no `message_stop`; new `test_midstream_upstream_http_error_uses_upstream_handler` raises `UpstreamHTTPError` mid-stream and asserts the mapped `event: error`.
- Gate: `tests/ --ignore=tests/test_main.py` 571 passed (570 + 1 new), 0 xfailed, 0 failed. black/isort (100) `--check` clean. No key-like literals added.
- Mutation checks (scratch copy /tmp/claude-501/mut2): swapping the UpstreamError and HTTPException except clauses fails `test_midstream_upstream_http_error_uses_upstream_handler` (1 failed, 10 passed); adding a `message_stop` after the 499 cancelled event fails `test_midstream_499_still_cancelled_event` (1 failed, 10 passed).
