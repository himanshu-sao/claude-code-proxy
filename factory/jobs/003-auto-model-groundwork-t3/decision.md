APPROVE

Sub-job 003-auto-model-groundwork-t3, branch factory/003-auto-model-groundwork-t3, final commit cf57e34, base 1d5a0e4.

## Reasoning

- Tests and format, which I re-ran myself.
  - `import src` resolves to `.../.claude/worktrees/003-t3/src/__init__.py`, so the worktree code is under test.
  - The offline suite plus `tests/test_signal_log.py` gave 101 passed.
  - `black --check` (line length 100) on `src/`, the test file and the script reported 19 files unchanged. `isort --check` was clean.
  - `git status` in the worktree shows only the untracked job folder files (`rework.md`, `round-1/` to `round-4/`). The real `logs/` holds only `proxy.log`.
- Scope and spec.
  - The diff is four new files: `src/core/signal_log.py`, `scripts/analyze_signal_log.py`, `tests/test_signal_log.py` and `build.md`. `endpoints.py`, `config.py` and `claude.py` are untouched.
  - build.md maps acceptance criteria 1-14 to tests and is STATUS: GREEN.
  - Spec deviations are all hardening that reviewers asked for, and each is test-covered. They are the name filter, the 0600 file with `O_NOFOLLOW`, the 0700 directory the module creates, the env clamps, the `_small_int` guard, the hardened analyzer and the explicit verdict rule.
- Spot-check of the PASS verdicts.
  - I read the round 3 and 4 reviews and the handler, env-clamp, `_header_map` and `_is_hash` code.
  - The code matches what the reviews claim. The handler opens with `O_APPEND|O_CREAT|O_NOFOLLOW` at 0600 and calls `fchmod`. `makedirs` uses `mode=0o700` and never chmods an existing directory. The clamps are 20 backups and 1 GiB.
  - I fed a real `starlette.datastructures.Headers` object with duplicate `x-api-key` headers to `_header_map`. It returns the first value, so the type T5 will pass works.
  - The round 4 api review drove 300 requests through both a plain and a T2-shaped request class. The records were identical field by field, the analyzer output was identical, and the leak greps were all 0.
  - The PASS verdicts are earned. I found nothing the reviewers missed.
- Review findings are all addressed. Rounds 1 to 4 raised: unfiltered names, file mode and symlink following, unbounded env limits, a huge-int record drop, analyzer crashes on valid-JSON garbage, hidden verdict thresholds, a 0755 directory, raw hash values on the terminal, and the T2 `output_config` declared-field bug. Each has a code fix and a test, and the round-4 reviews re-verified them.
- Integration. The orchestrator merged T1+T2+T3+T4 in a scratch tree with the real T2. The combined suite passed (190 tests, black and isort clean). An end-to-end check logged `oc_effort` correctly for four request shapes. The read order (declared attribute first, then `model_extra`, with a declared None not hiding an extra) is tested against both shapes. The orchestrator's merge check is the source for the 190-test figure. I did not reproduce it.
- Privacy trade-offs: I accept them.
  - Name filtering, not an allow-list. Allow-listing known field names would defeat the purpose of Phase 0, which is to discover which fields Claude Code actually sends. The filter admits only identifier-shaped names (`[A-Za-z0-9_.:/-]{1,64}`). Content, values, tool names and schemas never enter the record. The residual risk is that a client who deliberately names a key with a secret-shaped identifier gets that identifier logged. Only the local user running Claude Code can do that, and the file is 0600. This is acceptable for an opt-in, default-off diagnostic.
  - Hashes are 8 hex, unsalted. A short first message (for example "hi") can be confirmed by dictionary guess. The file is 0600 in a 0700 directory it creates, the log is off by default, and the hashes exist only for this capture. Unsalted is needed to compare hashes across restarts and rotated files. This is fine for Phase 0, but it must never become the production key (see Carry forward).
- Process.
  - The 4 rounds against a cap of 2 were each explicitly authorised by the user, so this is not a policy failure.
  - There is a real process observation. Round 4 existed only because T3 and T2 were reviewed in isolation. The integration bug showed up only when the orchestrator merged them. It was the right catch and the right fix.
  - Sub-jobs that touch the same request model should get a combined-tree check before their individual review rounds close. Doing it earlier would have cost one round, not four.
  - Rounds 1 to 3 each found a smaller security or hardening nit that a stricter first-round brief could have collapsed. Examples are the directory mode and `ascii()` on printed hashes. Review severity fell with each round, which is the expected pattern.
- Was a no-HTTP live review adequate? Yes, for what T3 delivers.
  - T3 is a module, a script and tests. Nothing in it speaks HTTP.
  - The reviewers ran real `emit_signal` calls in separate processes. They covered restart/append, 4 concurrent processes, rotation, clamps, unwritable path, symlink, umask 022/077/000, and the analyzer on empty, garbage, rotated and ESC-laden input.
  - The remaining gap is a real FastAPI request with real Claude Code headers. That belongs to T5's live review and is listed under Unverified.

## Unverified

- Behaviour inside a running proxy: event-loop cost of the blocking file write, behaviour with a real `Request` and real Claude Code traffic. T5's api-tester must cover these.
- Which fields and headers real Claude Code sends (`output_config.effort`, the session-id header, the request-class header). This is the point of Phase 0 and is still the research assumption from `answers.md`.
- The T1+T2+T3+T4 combined result (190 tests). I relied on the orchestrator's report and did not rebuild the scratch tree.
- Multi-worker uvicorn. Rotation is thread-safe but not process-safe. The proxy runs one process, so this is out of scope, but T6 must say so.
- Windows or other platforms without `O_NOFOLLOW` or `fchmod`. The code degrades by skipping them, and nothing was run there.
- Whether the user wants the 8-hex hashes kept long term. They are fine for this capture only.

## Carry forward

Where each deferred item is recorded now, and what is missing.

Recorded and sufficient:
- T5 must call `emit_signal` after validation, wrapped so it cannot raise, and offload the blocking write or state the trade-off. This is in `factory/jobs/003-auto-model-groundwork/answers.md`, section "Notes for T5 and job 004".
- Job 004 needs at least 64 bits, in memory only. Also in that section.

Missing or too weak. The orchestrator should fix these before T5, T6 or job 004 start:
1. The "Notes for T5 and job 004" section is an uncommitted modification in the main tree (`git status` shows `M factory/jobs/003-auto-model-groundwork/answers.md`). It also does not appear in the T5 or T6 `refined-prompt.md`. T5's prompt reads only "pass `request` and `http_request.headers` to the emit function once". Commit the note, and copy it into T5's prompt or spec, because a sub-job reads its own folder first.
2. T6 needs the following added to its prompt. Its prompt currently lists only the five env var names, "append-only, survives restarts, rotates at the cap, content-free, gitignored", and how to run the analyzer. It does not mention:
   - The clamps: `AUTO_SIGNAL_LOG_BACKUP_COUNT` at most 20 and `AUTO_SIGNAL_LOG_MAX_BYTES` at most 1073741824 (1 GiB). Invalid, empty or non-positive values fall back to the defaults 3 and 5242880.
   - File mode 0600. The log directory is 0700 only when the module creates it. An existing `logs/` (made 0755 by `src/core/logging.py`) is left alone.
   - Missing parent directories get default modes.
   - The file is not a symlink target: `O_NOFOLLOW` is used.
   - The privacy statement must be accurate. The record holds identifier-shaped field, header and key names (anything else becomes `other`), 8-hex unsalted hashes of the session id and of the first user message, and no values or text. A short prompt's hash can be dictionary-guessed.
   - The log is off by default, so documentation should say to keep the file local and delete it after the capture.
   - Rotation is single-process only.
   - How to run the analyzer: `python scripts/analyze_signal_log.py logs/auto_signal.log*`. The verdict needs at least 10 sessions and at least 10 sessions with 2 or more main-thread turns, with thresholds of constancy at least 95% and shared-session share at most 5%. Below that it prints "insufficient sample".
3. Job 004 needs a test that round-trips a real `emit_signal` hash through the analyzer's `_is_hash`. The current `_HASH_RE` is `[0-9a-f]{1,64}` and `emit_signal` produces 8 lowercase hex characters, so it matches today. No test ties the two together, and nothing is recorded anywhere. This is not in any file. Add it to the T5 or T6 spec, or to the job 004 notes. There is no 004 job folder yet, so `answers.md` is the only place a future 004 refiner will look.
4. Add one line to the same section saying that the 8-hex `fm_hash` and `sid_hash` must not be reused as the routing key. Job 004's key must be at least 64 bits and held in memory, and must be derived separately, not read back from the log.
5. T5's live review should check three things the T3 reviews could not. A real `Headers` object is handled (I confirmed `_header_map` copes with it). A failing log path does not change the status or body of `/v1/messages`. A 422 request is not logged, because `emit_signal` must come after validation.
6. For the factory process: when sub-jobs touch the same request model, run the combined-tree merge check before the individual reviews close.
