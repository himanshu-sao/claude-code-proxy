VERDICT: PASS

Tests: 86 passed (offline suite plus test_signal_log.py, shared venv python 3.14, `src` resolves inside the worktree). black and isort are clean. The worktree has only the untracked `round-1/` folder. I did not edit anything outside this file.

**Round-1 fix 1: analyzer exit 0 on valid-JSON garbage. Fixed.**
- I ran `python -I scripts/analyze_signal_log.py` on crafted files under `$TMPDIR`.
  - Lines: `{"sid_hash":[1],"fm_hash":[2]}`, dict `sid_hash`, `body_fields:[[1]]`, mixed `header_names`, list/dict `req_class`, `reasoning_effort` and `think_type`, a string `agent` and `est_tokens`, `1e999`, `NaN`, `null`, `5` and `"str"`.
  - Nesting: `[` x 300000, `{"a":` x 100000, `[`x5M plus `]`x5M, and a 10 MB `sid_hash` string.
  - Every run exited 0 with an empty stderr and all 7 sections printed. The same files also exit 0 under system Python 3.9.6. The `RecursionError` catch is at `analyze_signal_log.py:44`.
  - `1e999` and `NaN` print as `inf` and `nan` in the stats line, which is harmless.
- The new garbage test (`tests/test_signal_log.py:~735`) really reaches the old crash paths: list-valued hashes, `[[1]]` names, and the deep-nesting lines. It asserts returncode 0, no `Traceback`, and all sections.

**Round-1 fix 2: verdict thresholds and sample sizes. Fixed.**
- `analyze_signal_log.py:233-266` prints the rule (>=95%, <=5%, at least 10 sessions overall and 10 with 2+ main-thread turns). It then prints the measured values with sample sizes, then the verdict. The constants are `MIN_CONSTANCY`, `MAX_SHARED` and `MIN_SESSIONS` (`:27-29`).
- The insufficient-sample branch is checked before the usable branch. I ran 1 session x 2 turns, and it printed "insufficient sample".
- The three branches each have a test: usable (12 sessions x 3 turns, asserts the measured line text), insufficient, and not-usable-when-shared. The usable test would fail if the sample gate were dropped or the thresholds inverted.
- The criterion-12 test change (`"NOT shown to be usable"` to `"insufficient sample"`) does not weaken it. Its fixture has only 4 sessions, so "insufficient sample" is now the correct output. The (a)/(b) assertions that criterion 12 actually specifies are unchanged (3-session group, main-thread 100% against all-records 0%, `{2: 1}`). The not-usable branch is covered by the new test.

**New code: handler `_open` override (`signal_log.py:336-347`). Robust.**
- Overriding `_open` is a de-facto stable hook. `FileHandler._open` is called with no arguments from `emit`, `shouldRollover` and `doRollover` on 3.9 through 3.13. The override returns a text stream, which is what the stdlib callers expect.
- It ignores `self.mode` and `self.errors`. That is fine here because `mode="a"` is fixed and `errors` is None.
- I ran the same probe on system 3.9.6, uv 3.13.13 and 3.14. It covered a pre-existing 0644 file, rotation at 300 bytes with backup 2, a dangling symlink and a symlink to a live file. Results were identical on all three:
  - `auto_signal.log`, `.1` and `.2` are all 0600. The pre-existing 0644 file was tightened by `fchmod`.
  - A dangling symlink did not create its target.
  - The live-symlink victim stayed "untouched".
  - Nothing raised into the caller.
- Descriptors: after 3 emit/`reset_for_tests` cycles, `/dev/fd` count grew by 0. The `except Exception: os.close(fd)` path covers a failed `fdopen` or `fchmod`. `-X dev -W error::ResourceWarning` gave no warnings from the module (the only warnings came from my own probe's `open()` calls).
- Portability: `getattr(os, "O_NOFOLLOW", 0)` and `hasattr(os, "fchmod")` degrade cleanly on Windows. On Linux, `O_NOFOLLOW` on a symlink raises ELOOP. That propagates out of `emit()` into `handleError`, which logs at DEBUG, so the failure is silent, as the spec wants. `test_symlink_at_log_path_is_not_followed` uses a real symlink and a real file. `test_log_file_is_created_0600` also uses real files, with no mocks.
- I did not run it on Linux. This is a reasoned judgement from the stdlib behaviour, not a run.

**New code: name filter, env clamps, int guards. Correct.**
- `_safe_name` (`:91-95`) uses `fullmatch` on `[A-Za-z0-9_.:/-]{1,64}`. Non-str values, empty strings, spaces, ESC, newline, unicode and 65-character names all become "other". Real model ids such as `z-ai/glm-5.3:free` and header names pass. It is applied to `body_fields`, `header_names`, `oc_keys`, `meta_keys` and `model`.
  - Residual risk, accepted: a client can still put a 64-character identifier-shaped string in a field-name position. That is inherent to logging names at all.
- `_int_env` (`:62-70`): invalid or non-positive gives the default, and above the maximum it clamps. Tested at 5000000 and 10**15, at the boundary (20), and for abc/0/-5/empty.
- `_small_int` (`:98-102`) excludes bool, float and values >=2**53. `10**5000` no longer drops the record.
  - On Python 3.11+ `json.dumps` of a huge int would otherwise raise because of the int-to-str digit limit. The test covers it end to end.

**Non-blocking nits (no change required for PASS).**
- The analyzer prints raw `sid_hash` and `fm_hash` strings with `%s` (`:210`). They are only checked as non-empty `str`, so a hand-crafted line with `"fm_hash":"f\u001b[2Jx"` emits a raw ESC to the terminal. I confirmed this. Names and enum values go through `ascii()`, so this is inconsistent. The module never writes such hashes, so the risk is low. A one-line fix would be to make `_is_hash` require `[0-9a-f]{8}`, or to print with `ascii()`.
- `test_analyzer_verdict_not_usable_when_shared` does not assert returncode 0. Trivial.
- Carried over from round 1: the sentinel test never exercises the str form of `system`, and the race test is weak. Neither affects correctness.

Docs: no user-facing docs are required from this job. `.env.example` and README entries for the two new env vars are deferred to the docs task (criterion 14). The clamps, 20 for backup count and 1 GiB for max bytes, should be mentioned there.
