# Answers (from the user, 2026-11-13)

1. Pre-first-byte read: **every streamed request** (read the upstream's first chunk before returning response headers).
2. Upstream `retry-after` above 60: **pass through unchanged**. Only our own 429 (all local keys exhausted) is capped at 60.
3. Assumptions 1-11 in refined-prompt.md: confirmed as written (the user approved the design in the previous session; "proceed with your assumptions").

# Orchestrator notes (not user answers)

- T1 (exhausted keys 429 + Retry-After + async getter + import-time client removal) and T2 (proxy.log append) are ALREADY DONE and merged into `feat/virtual-auto-model` at 67de01a. Branch `factory/005-error-contract` is cut from that commit. They are not sub-jobs; keep their tests as regression only.
- `config.seconds_until_key_available()` already exists in `src/core/config.py` and is used by endpoints.py for our own Retry-After.
- Run all python with the shared venv: `~/Work/src/extra/himanshu-sao/claude-code-proxy/.venv/bin/python -m pytest ... -p no:cacheprovider` with `OPENAI_API_KEY=test-key`, from the job's worktree. Offline suite command: `tests/ --ignore=tests/test_main.py` (baseline 377 passed, 4 xfailed). Never run tests from the main checkout (importing src.core.logging touches logs/).

# Size gate decision (user, 2026-11-13)
- 005-error-contract-b: the SIZE WARNING (4 files, 11 criteria) is accepted. Proceed to build as specified.
- 005-error-contract-c: the SIZE WARNING (5 files, 13 criteria) is accepted (user, 2026-11-13). Proceed to build as specified.

# Orchestrator decision (not a user answer)
- 005-error-contract-c removes ONLY the four strict `xfail` decorators (and their stale reason text) on `test_stream_upstream_error_is_visible_to_client[400|422|503|429]`, leaving the assertion unchanged, because the errors are injected before the first chunk and now return a real HTTP status. Goal G3 therefore moves from slice D to slice C; slice D keeps G4, G6, G12.

# Merge plan (user, 2026-11-14)
- Finish slice D first. Then a fresh review agent reviews the whole integration branch `factory/005-error-contract` (and the worktrees), and only then it is merged into `feat/virtual-auto-model`. Merging into `main` stays a separate PR the user approves (never merged directly).

# Whole-job review outcome (2026-11-14)
- whole-review.md: VERDICT CHANGES. whole-api.md: VERDICT CHANGES. Orchestrator reproduced: (1) two slice-C tests error on Python 3.9 (569 passed, 2 errors); (2) a lone surrogate in upstream text makes error_json(...).encode() raise UnicodeEncodeError; (3) client.py yields [DONE] unconditionally after the SDK loop, so a stream that closes cleanly with no finish_reason looks like a normal finish.
- User decision: a stream that ends with no finish_reason seen is treated as an ERROR (one `event: error`, no message_stop), not as success. Risk accepted by the user: a provider that omits finish_reason would show errors on good replies; to be checked against the real NVIDIA models before the proxy is restarted on this code.
- Fixes are done as sub-job 005-error-contract-e on the integration branch, with the full review loop.

# Hands-free run policy (user, 2026-11-14, answered in the forked session)
- Driver: the forked session drives the rest of the loop. The original session ([local_22b3ae0f-5cc3-477e-8b36-3e6b35073c9e]) must not be given work for this job.
- Sub-job E (005-error-contract-e): FULL review loop (security, code, api, then approver), cap 2 rounds. Builder E had stopped when the previous session ended; its 3 commits (0380c1a, a7fdf2d, 655f78a) were verified by the orchestrator: 592 passed on Python 3.14 and on 3.9.6, lint clean.
- Pre-authorised once E is APPROVED and the full offline suite is green on BOTH 3.14 and 3.9: (1) merge `factory/005-error-contract` (A-D plus E) into `feat/virtual-auto-model`; (2) commit factory/board.json and factory/jobs/ to `feat/virtual-auto-model`. NOT pre-authorised: pushing to origin, opening a PR, merging into main (never directly).
- Live checks: the user will restart the proxy on 8082 themselves, then ask for ALL live checks together. Pre-authorised now: run the real `claude` CLI against a scratch proxy + fake upstream on a free port (no paid tokens). NOT authorised yet: the real NVIDIA run (paid) and the restart; they stay a TODO for after the user's restart.
- On failure (CHANGES after round 2, ESCALATE, or red tests after a merge): allow ONE extra fix round beyond the cap of 2, then stop and report; do not revert or force anything.
- Follow-ups from the whole-job review: write them to factory/backlog.md as unchecked items (do none now).
- Cleanup: REPORT ONLY (list safe-to-remove worktrees and stale branches with the exact commands; delete nothing).
- Stale items: update the offline test command in CLAUDE.md (use `tests/ --ignore=tests/test_main.py`) and the suite counts in QUICKSTART, as a small final commit on feat/virtual-auto-model. Job 002 is left alone (mention it only).
