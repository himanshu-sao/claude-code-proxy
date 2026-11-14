APPROVE

- Scope verified: `git diff 6c82d50 factory/005-error-contract-d` touches only `src/conversion/response_converter.py`, `tests/test_midstream_errors.py` and `QUICKSTART.md`. The tip is 1e99bd1.
- `src/` is unchanged since round 1. The 50c2be1 to 1e99bd1 delta is only QUICKSTART (2 lines) and the tests.
- The converter change is small and correct. `except UpstreamError` sits before `except HTTPException`, which matters because `UpstreamHTTPError` is both. It emits one `event: error` and returns, with no `message_stop`. The generic handler now sends only `Streaming error: <TypeName>`, so raw exception text no longer reaches the client. The 499 cancelled path is unchanged.
- Round-1 CHANGES (the two QUICKSTART wording fixes) are fixed:
  - The unverified "Claude Code retries" claim is gone.
  - The 401 and 422 `{"detail": ...}` exceptions are now stated.
  - The optional tests were added too.
- All round-2 verdicts (code, api, security) are PASS lines with evidence.
- I re-ran the tests in a scratch copy from `git archive`. `src` resolved to the copy, and the result was 571 passed with 0 xfailed.
- The mutation checks in build.md cover the sanitising, terminal-event and handler-order behaviours.

Non-blocking notes, accepted as follow-ups to track:
1. A lone-surrogate character in an upstream message can abort the stream while the error event is being built.
2. The catch-all handler's traceback logging can include a chained cause. This is a log-hygiene issue only, not client-visible.
3. For an RST or EOF mid-stream, the client sees `Unexpected error: <SDK text>`. Better wording is a nicety.
4. There is no end-to-end TestClient test for a mid-stream failure through `endpoints.py`. The converter is tested directly.
5. Claude Code's live behaviour on a mid-stream `event: error` with no `message_stop` is unverified. QUICKSTART says so honestly. Check it manually at some point.

Before merging, the orchestrator must:
- Merge the branch tip 1e99bd1. The job folder is untracked, so it is not part of the commit.
- Keep the ordering of the 005 slices a, b, c and d.
- Re-run the full suite on the integrated result. Expect 571 passed for this slice's tree.
