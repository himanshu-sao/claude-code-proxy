APPROVE

Sub-job 003-auto-model-groundwork-t5, branch factory/003-auto-model-groundwork-t5, build commit b949596, spec 87143c9, base 1765c8e.

## Reasoning

- Tests and format, re-run by me.
  - `import src` resolves to `.../.claude/worktrees/003-t5/src/__init__.py`.
  - The offline suite (effort_mapper, endpoints, context_manager, model_manager, signal_log) gave 214 passed.
  - `black -l 100 --check src/ tests/test_endpoints.py` is clean, and so is isort with `--profile black -l 100`.
  - The worktree `logs/` holds only `proxy.log`, so no `auto_signal.log` was created. `git status` shows only the untracked `round-1/` review files.
- Scope.
  - `git diff 87143c9 HEAD` shows only `src/api/endpoints.py` (+19), `tests/test_endpoints.py` (+272, 0 lines removed) and `build.md`.
  - `signal_log.py`, `config.py` and `claude.py` are untouched. T1's `logger.info(... reason=%s)` call is not edited. No new env var or config field was added.
- Source change, read directly.
  - There is one private helper `_emit_signal_safe` and one call site.
  - The call sits inside `create_message`'s `try`, right after T1's `reason=` INFO line and before `convert_claude_to_openai`, the disconnect check and the stream split.
  - The helper evaluates `http_request.headers` (the real Starlette `Headers`) and `model_manager.is_auto_alias(request.model)` inside `try/except Exception`. On failure it logs `signal log skipped: <ExcClass>` at DEBUG, which has no `reason=` and no exception text.
  - The helper calls `signal_log.emit_signal` through the module, so tests can patch it.
- Acceptance criteria 1-9 are met.
  - I re-ran the tests, which cover criteria 1 to 8. Criterion 9 holds: the real `logs/auto_signal.log` was not created and only the two intended files changed.
  - The security reviewer, code reviewer and api reviewer each re-ran the checks independently and agree.
  - The code reviewer's mutation checks show the tests are not decorative. Removing the call gives 16 failures. Calling it on non-stream requests only gives 6. Calling it twice gives 12. Hard-coding `auto=False` gives 4. Removing the guard gives exactly 4 failures, as the orchestrator also found.
- The PASS verdicts are earned. I spot-checked them against the files and the diff, and I did not find anything the reviewers missed.
  - The security review sent hostile input through the real handler: a 10 KB model name with a newline and a forged `AUTOSIGNAL` text, 305 headers and duplicate session ids. The result was 1 physical line, names collapsed to `other`, and first-value-wins for the session id.
  - It also showed that 401 and 422 requests write 0 lines, and that disk use is bounded by the env clamps rather than by request count.
  - The api review covered Claude Code-shaped requests, 300 sequential requests with modes 0600 and 0700, forced rollover, six failure modes against a log-off baseline, an upstream raise, the off values, T1 behaviours with the log on and off, and the analyzer.

### The eight points

1. **In-process api evidence for an opt-in, off-by-default diagnostic.** It is adequate.
   - The things that could hurt a user are all covered in-process. These are the response being unchanged when logging fails (6 failure modes, stream and non-stream), a 422 or 401 not being logged, nothing being created when the switch is off, and nothing sensitive reaching the file.
   - The remaining gaps (see Unverified) can only produce a missing or odd diagnostic line, or a small latency cost on a path that is off by default. None of them can change a response, and the guard catches every exception type from the helper.
   - The api review is marked PASS and I accept that. It is not equivalent to a live run, and decision.md says so under Unverified.
2. **T3 approver's requirements for T5.** All five are met and tested.
   - Called after validation and wrapped: the call is inside the handler `try`, behind the helper's guard. 422 and 401 never reach the handler, and the tests prove it (`test_signal_log_422_is_not_logged`).
   - Event-loop trade-off: stated in spec section 2 and in the code comment.
   - Real `Headers` object: `test_signal_log_header_privacy` runs through TestClient. The security and api reviews also tested duplicates.
   - No second `reason=` line: `test_reason_line_once_with_signal_log_on` and the `reason=` count asserted in the failure test.
   - A failing log path leaves `/v1/messages` unchanged: cases (a), (b) and (c), each stream and non-stream, compared with a log-off baseline.
3. **Inline, not an executor.** I accept it.
   - The reviewers measured about 0.12 ms added typical, about 8 to 10 ms for a 2 MB body, and 1.3 to 1.8 ms at a rollover.
   - It only runs when the switch is on. The cost is small next to the handler's own sync work and an upstream LLM call.
   - Inline gives deterministic line order, which the analyzer depends on, and leaves nothing pending at shutdown.
   - An executor would add exception-retrieval and ordering complexity for little gain.
   - The cost is bounded and the log is opt-in. A multi-ms stall at a 5 MB rollover is acceptable.
4. **`sys._getframe(1).f_code.co_name` in the 5(c) guard test.** Record it, do not fix it before merge.
   - The spec itself prescribes this form.
   - It fails loudly rather than vacuously. If the helper is renamed or the evaluation moves, the wrapper never raises, so the `spy == []` and `signal log skipped: RuntimeError` assertions go red.
   - Guard removal produces exactly 4 failures, so the test does its job today.
   - The sturdier code-object comparison is a cheap optional follow-up. It is listed under Carry forward.
5. **Autouse fixture only in `tests/test_endpoints.py`.** Carry forward, not blocking.
   - I checked the other modules that mention the route. `tests/test_compat_endpoints.py` has no offline POST to `/v1/messages`. `tests/test_main.py` posts to `http://localhost:8082/v1/messages` and is a live-integration test.
   - The security reviewer ran 239 tests with `AUTO_SIGNAL_LOG=1` exported across six modules, and `logs/` stayed clean.
   - The residual risk is purely about future tests.
   - One real operational note: running `tests/test_main.py` against a user's own running proxy that has `AUTO_SIGNAL_LOG` on will add lines to that proxy's real log. The test does not control that proxy, so nothing in a unit test can prevent it. This belongs in the docs note for T6 as a caveat.
6. **Small inaccuracies.** None blocks the merge.
   - The helper docstring says "No-op unless AUTO_SIGNAL_LOG is on", but `is_auto_alias` is still evaluated. That is a cheap pure call, and the wording is slightly loose. Fix it in passing, or leave it.
   - `build.md` says +16 lines, but the diff is +19 (a documentation slip in a job artifact).
   - The log-injection surface is T1's `reason=` INFO line logging the raw `request.model` into `proxy.log` and the console. It is pre-existing and not T5's to fix, and T5 does not widen it. The signal log itself is clean, because names that are not identifier-shaped are logged as `other`. It goes to Carry forward. The T3 and T4 approvers had already flagged it as optional hardening.
7. **Orchestrator's independent verification.** It matches mine.
   - The 214-test count matches. I did not repeat the other checks: the run with `AUTO_SIGNAL_LOG=1` exported, the guard-removal check, and the end-to-end probe of 1 line for a valid request, 0 for a 422, and mode 0600.
   - The reviewers' independent runs support those results. The code reviewer confirmed the guard-removal check, and the security reviewer ran the `AUTO_SIGNAL_LOG=1` export.
8. **T6 dependency.** T5 adds no env var, so the five variables T6 lists remain the complete set. The T6 prompt does not carry T5's behaviour. See the T6 items under Carry forward.

## Unverified (did not run; no local port binding was allowed)

- Real uvicorn/h11 header parsing: duplicates, casing, order, and header merging. TestClient (httpx) builds these itself.
- The real default `_log_path()` resolving to `<root>/logs/auto_signal.log`, with a 0600 file and a 0700 directory created inside a running proxy. Every test and probe overrode `_log_path`. The modes observed were on scratch paths.
- Event-loop latency under concurrent load and during a rollover under load. All timings were sequential, in-process, with a stub upstream and TestClient overhead.
- Behaviour at uvicorn shutdown, and real client disconnects (the 499 path with the call placed before the disconnect check). A patched `is_disconnected` gave 499 with 1 line.
- A real HTTP upstream error (4xx/5xx from a provider). Only a stub that raises was used.
- A live-socket repeat of "failing path leaves `/v1/messages` unchanged", "a 422 is not logged" and "`AUTO_SIGNAL_LOG` unset creates no file". In-process equivalents all passed.
- Python 3.9. Only the venv interpreter was run. The code uses no `X | Y` or `match`, and `sys._getframe` is fine.
- The dotenv case itself: the local `.env` has no `AUTO_SIGNAL_LOG*` lines. The `delenv` plus `_log_path` patch makes the fixture robust anyway.
- The full `uv run pytest tests/` suite, which needs a live proxy on :8082. I ran the offline subset only.

## Carry forward

For T6 (docs). Its prompt covers the five env vars and the T3 detail well, but nothing from T5.
- Add that the call runs after auth and validation, so 401 and 422 requests are never logged. An accepted request is logged once, even if the upstream then fails.
- The log covers all models (alias, tier-map and pass-through names), and stream and non-stream requests alike.
- With `ANTHROPIC_API_KEY` unset, any network peer can append bounded records, because the proxy's trust model is open. Say to keep `HOST` local or set the key when the log is on.
- Cost and trade-off: the write is inline on the event loop. It is about 0.1 ms typical, about 8 to 10 ms for a 2 MB body, and about 2 ms at a rollover.
- `AUTO_SIGNAL_LOG` is read at call time but `.env` is loaded at import, so changing `.env` needs a restart. Exported env changes also need a restart.
- Running the live test `tests/test_main.py` (which posts to `localhost:8082`) against a proxy with the log on adds lines to that proxy's real log.
- The README "Environment Variables" section and `.env.example` need only the five already listed variables. T5 adds none.
- The T2 addendum asks for a cheap `reasoning_effort: "bogus"` 422 test. T5's `test_signal_log_422_is_not_logged` already uses an invalid `reasoning_effort`, so T6 need not add one.
- T6 should treat the T3 decision.md carry-forward items as already in its prompt. They are present in the addendum.

For job 004.
- Everything already recorded in `factory/jobs/003-auto-model-groundwork/answers.md` stands. That is: the 8-hex hashes must not be the routing key, the `_is_hash` round-trip test, the process lesson on combined-tree checks, and sanitising the model name in T1's request log line (the pre-existing log-injection surface).
- The sturdier 5(c) guard: replace the `co_name` comparison with `sys._getframe(1).f_code is endpoints._emit_signal_safe.__code__`. This is optional.
- Optional: move the `signal_path` fixture to `tests/conftest.py`, if another offline module ever POSTs to `/v1/messages` through TestClient.
- Optional: log a one-time WARNING on the first emit failure. At the default INFO level a persistently failing write (disk full, bad permissions) is invisible to an operator who enabled the log.
- A live-socket pass (real uvicorn, real Claude Code headers, real default `_log_path`) once local binding is allowed, covering the Unverified items above.
- Correct the helper docstring ("no-op unless the log is on") and the `build.md` "+16 lines" figure, if anyone touches those files.

## Required before merge

NONE.
