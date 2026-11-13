VERDICT: PASS

Scope: delta `git diff 3bb73e1 HEAD` (commit 1a8143b). It touches only `build.md`, `scripts/analyze_signal_log.py`, `src/core/signal_log.py` and `tests/test_signal_log.py`. Both rework items are done as rework.md says, and nothing else changed.

Tests and format (worktree, shared venv python, `import src` resolves to `.../.claude/worktrees/003-t3/src/__init__.py`): the offline subset plus `tests/test_signal_log.py` gave 89 passed. black at line length 100 reports "19 files would be left unchanged". isort `--check` is clean. `build.md` line 1 is `STATUS: GREEN`.

1. Log directory mode: done.
- `src/core/signal_log.py:363` is now `os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)`. The comment at :361-362 states the caveats: the umask still filters the mode, only the leaf gets it, and missing parents get default modes. Nothing chmods an existing directory. `build.md` records the same caveats.
- `tests/test_signal_log.py:842` is the `umask_022` fixture. It does `old = os.umask(0o022)`, then `yield` inside `try`, then `os.umask(old)` in `finally`, so the umask is restored on failure. `os.umask` is process-global, but the suite has no threads or xdist, and every mode-checking test sets its own umask. Test order and parallelism are not a concern. xdist would use separate processes anyway.
- Mutation check on a copy of the tree in `$TMPDIR`, with `mode=0o700` removed: `test_created_log_directory_is_0700` (:851) FAILS, because the directory comes out 0o755. `test_existing_log_directory_is_not_tightened` (:865) passes either way. That is correct, since it guards against over-tightening and does not test the change.
- Both tests are skipped when `os.fchmod` is missing, which matches the module's own POSIX gating.

2. Analyzer hash handling: done.
- `scripts/analyze_signal_log.py:21` adds `import re`. :27 adds `_HASH_RE = re.compile(r"[0-9a-f]{1,64}")`. :167 makes `_is_hash` use `fullmatch`. :212 prints `ascii(fm)[1:-1]`.
- Mutation check: with `_is_hash` reverted and the `ascii()` removed, `test_analyzer_does_not_print_raw_escape_from_hash_values` (:880) FAILS. Reverting only the `ascii()` leaves it passing, and reverting only the regex also leaves it passing. So each guard alone is enough for this test, and neither is isolated by it. That is non-blocking, and it matches the "or both" wording in rework.md.
- The test writes an `sid_hash` and an `fm_hash` that each contain `\u001b[31m`. It asserts returncode 0, then `"\x1b" not in res.stdout` and `"\x1b" not in res.stderr`, so it covers both streams. `_run` uses `capture_output=True, text=True`. It does not assert that the report sections are printed. That is fine for its purpose.

Regression checks:
- I generated logs with the real `emit_signal` (fm_hash such as `acdda044`, 8 lowercase hex): 12 sessions x 3 turns, in two variants. I ran the old analyzer (`git show 3bb73e1:scripts/analyze_signal_log.py`) and the new one on each. The full outputs are byte-identical (empty diff) and both exit 0.
  - Unique first messages: "usable (thresholds met)", constancy 100.0%, shared 0.0%.
  - Shared first message: "NOT shown to be usable (thresholds not met)", shared 100.0%.
- The narrowed regex drops uppercase or non-hex hashes. That is intended, and the module cannot produce them (`hexdigest()[:8]`).
- Other `%s` prints in the analyzer, none of which print a raw hash or name:
  - :54 prints the path and the exception text to stderr. The path comes from the operator's own arguments.
  - :84 prints a constant section title.
  - :73 prints numeric stats.
  - :124 is already `ascii()`-wrapped.
  - :183, :184 and :269 print counts and percentages.
  - `freq_section` and the other name sections use `ascii()`.
- `src/api/endpoints.py` and `src/core/config.py` are untouched in the delta and against main. `factory/board.json` is not in the delta. It shows in `main...HEAD` only because the earlier decompose commit 1d5a0e4 added it.
- Thresholds, verdict rule, hash length, salting, name filter and env clamps are not in the delta. The worktree has only the untracked `rework.md`, `round-1/`, `round-2/` and `round-3/`.

Non-blocking: the `ascii()` guard at :212 is unreachable with the current `_is_hash` and has no test of its own. It is defensive only.
