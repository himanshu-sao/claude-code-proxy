VERDICT: CHANGES

Tests: 75 passed (offline suite plus test_signal_log.py, shared venv python, `src` resolves inside the worktree). black and isort are clean on src/, the test file and the script. `ast.parse(feature_version=(3,9))` accepts all three new files. I found no `X | Y` unions and no `match`. python3.9 is not installed here, so there was no runtime check on 3.9. `src/api/endpoints.py` and `src/core/config.py` are untouched. `logs/auto_signal.log` is ignored (`.gitignore:179`).

Two small fixes are needed, both in `scripts/analyze_signal_log.py`.

- **Analyzer exits non-zero on garbage that is valid JSON (criterion 11, "exits 0 on garbage").** I reproduced three crashes, each with exit 1 and a traceback:
  - `AUTOSIGNAL {"sid_hash":[1],"fm_hash":[2]}` raises `TypeError: cannot use 'list' as a dict key` at `analyze_signal_log.py:183-185`. `sessions_by_fm[r["fm_hash"]]` and `set(r["sid_hash"] ...)` assume the values are hashable.
  - `AUTOSIGNAL {"body_fields":[[1]]}` raises `TypeError: unhashable` at `analyze_signal_log.py:87`, where `set(names)` runs over list-valued entries.
  - `AUTOSIGNAL [[[[...` with about 200k brackets raises `RecursionError` at `analyze_signal_log.py:39`. `json.loads` raises `RecursionError`, and the code only catches `ValueError`.
  - Fix:
    - In `load_records`, catch `(ValueError, RecursionError)`.
    - Accept `sid_hash` and `fm_hash` only when they are `str`. Treat the `body_fields` and `header_names` entries as strings, e.g. `str(n) for n in names`, with no `set()` over raw items.
    - Alternatively, wrap each section in a try/except that prints a one-line "section skipped" message.
  - Add one test with such a line. The current garbage test (`test_signal_log.py:595`) only has lines that fail `json.loads` or are non-dicts, so it never reaches these paths.
  - The module itself cannot write these shapes, so the risk is low. It is still an explicit criterion, and the fix is cheap.

- **The verdict thresholds (95% and 5%) are not visible anywhere a reader will look.**
  - They exist only in code (`analyze_signal_log.py:224-225`).
  - The printed verdict says "near 100%" and "near 0%". The module docstring and the usage text don't give the numbers either.
  - `build.md` mentions them, but whoever reads the script output in job 004 will not see `build.md`.
  - Fix: print the thresholds in the verdict, e.g. "usable = main-thread constancy >= 95% and shared-session share <= 5%", and show the measured values next to them.
  - Also print the sample size behind the verdict, or add a minimum-sample caveat. With 1 session of 2 turns, constancy is 100% and sharing is 0%, so the script prints "usable".
  - The only verdict assertion (`test_signal_log.py:648`) covers the NOT-usable branch. Add one test for the "usable" branch. I ran it by hand on 30 clean sessions of 3 turns each, and it printed "usable".

What I checked and found fine:

- **Criteria 1, 2, 7, 8, 9, 10 (module behavior).**
  - The tests use real files and a monkeypatched `_log_path`, not mocks.
  - The rotation test (300 bytes, backup 2) would fail if there were a `.3` or no rotation.
  - The reset-then-emit test would fail if the file were truncated.
  - The unwritable-path tests run the real error paths. The file-in-place-of-directory case is caught in `emit_signal`, and the read-only directory goes through the `handleError` override. The `Traceback` check on captured stderr would trip on the stock logging error output.
  - The race test is weak. It uses 2 threads on a barrier and could pass without the in-lock re-check. The double-check in `_ensure_handler` is correct, so I'm not asking for a change.
- **Criterion 3 (content-free guarantee).**
  - `build_signal_record` only emits names, counts, booleans, enum-filtered values and two prefixed 8-hex hashes. Free text reaches the record only through `_cap` on `model`, the body, header and metadata key names, and the `oc_keys` names. All of these are capped at 64 characters and 50 entries.
  - The sentinel test would fail if a field leaked. It covers the system list form, user text, tool_use key and value, tool name, description, property name and value, tool_result, base64, metadata value, extra value, `output_config` values, garbage request class, and header values.
  - Gap: `sys_str` (the string form of `system`) is defined at line 111 but never put in the body, so it is checked trivially. Add `system` as a str in a second small test. This is minor and not blocking.
- **Criterion 12 and scripts policy.**
  - The two-measurement test is real: 3 sessions sharing one `fm_hash`, plus a session with 4 main-thread turns and 1 subagent turn. It asserts the main-thread figure is 100% and the all-records figure is 0%. It would fail if the two were conflated.
  - The analyzer separates (a) repeat rate (distinct `sid_hash` per `fm_hash`) from (b) constancy (distinct `fm_hash` per `sid_hash`, main-thread only and all records), and reads multiple files, including rotated ones.
  - The script is stdlib-only, offline, and not collected by pytest. It is not under `tests/` and does not match `test_*.py`, and there is no pytest `testpaths` override.
  - Running it through `subprocess` with `sys.executable` is acceptable. The `scripts/` rule is aimed at live-verification scripts that need a running proxy or real keys. This one is deterministic and offline, and it needs a test to prove criterion 12.
- **Size and shape.**
  - `signal_log.py` is 376 lines and `tests/test_signal_log.py` is 648. Both are reasonable and the tests are well sectioned.
  - `build_signal_record` uses closures with `nonlocal extra`, which is a bit unusual for this repo but readable. Not blocking.
- **Docs.** Docs and `.env.example` for the two new env vars are deliberately deferred to the docs task (criterion 14), so I'm not flagging them here.
