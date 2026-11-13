STATUS: GREEN

# Build report - 003-auto-model-groundwork-t3

## Files changed (all new)
- `src/core/signal_log.py` - `build_signal_record`, `emit_signal`, `_log_path`, `reset_for_tests`. Content-free record, lazy `auto_signal` logger (`propagate=False`, `RotatingFileHandler(mode="a", delay=True)`, double-checked creation under a `threading.Lock`, `handleError` overridden to DEBUG on `proxy`). Env read at call time; imports nothing from `src.core.config`/`logging`.
- `scripts/analyze_signal_log.py` - stdlib-only analyzer (sections per spec, (a) repeat rate and (b) constancy computed separately, main-thread vs all-records, verdict lines). Exit 2 only with no args.
- `tests/test_signal_log.py` - 39 tests (50 after rework round 1) covering acceptance criteria 1-13 (tmp_path + monkeypatched `_log_path`; analyzer run via `subprocess` with `sys.executable`).
- `src/api/endpoints.py` and `src/core/config.py` untouched (wiring is T5). No docs/.env.example changes (docs task).

## Testing
Run from the worktree with `OPENAI_API_KEY=test-key`, shared venv python (`python -c "import src; print(src.__file__)"` printed a path inside the worktree).
- `python -m pytest tests/test_signal_log.py -q` -> 39 passed.
- `python -m pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py tests/test_signal_log.py -q` -> 75 passed.
- `python -m black --check src/ tests/test_signal_log.py scripts/analyze_signal_log.py` and `python -m isort --check src/ tests/test_signal_log.py` -> clean.
- `git check-ignore logs/auto_signal.log` -> ignored (`.gitignore:179`). The real `logs/` gained no `auto_signal.log`.

## Acceptance criteria
1-13 pass via the tests above (1 disabled; 2 one line/no propagation/no newline; 3-4 sentinel + fields; 5 hashes; 6 robustness incl. 5 MB; 7 append/restart/race; 8 rotation + invalid env; 9 missing/unwritable dir; 10 LOG_LEVEL; 11-12 analyzer; 13 offline suite). 14: black/isort pass, path is gitignored.

## Notes / deviations
- No spec deviations. Interpretation choices: `think_type` is None when `thinking` is absent; `oc_keys` is `[]` when `output_config` is absent/not a dict; enum values are lowercased before logging; `fm_stripped` is always present (false when no user message). `model` is capped at 64 chars like other strings.
- The read-only-directory test is skipped when run as root.
- Verdict thresholds in the analyzer: "near 100%" = >=95% constant, "near 0%" = <=5% shared sessions (my choice; spec gives no number).

## Rework round 1
All tests below are in `tests/test_signal_log.py`. Final run (worktree, shared venv python, `OPENAI_API_KEY=test-key`, `import src` resolves in the worktree): `python -m pytest tests/test_signal_log.py -q` -> 50 passed; offline subset plus `tests/test_signal_log.py` -> 86 passed; `black --check` and `isort --check` clean; all three files parse with `ast.parse(feature_version=(3, 9))`. `endpoints.py`, `config.py` and `board.json` untouched; real `logs/` has no `auto_signal.log`.

Security
1. Names not content-free: `_safe_name` (pattern `[A-Za-z0-9_.:/-]{1,64}`, else `"other"`) now filters every name in `body_fields`, `header_names`, `oc_keys`, `meta_keys` and `model` (the old `_cap` is gone). Tests: `test_hostile_names_are_logged_as_other` (marker text, spaces, ESC and newline, unicode and RLO, 65 chars, empty, in all five places, plus an end-to-end emit), `test_legitimate_names_pass_through`.
2. Permissions and symlink: `_SignalFileHandler._open` uses `os.open(..., O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW, 0o600)` plus `fchmod 0o600`. Tests: `test_log_file_is_created_0600`, `test_symlink_at_log_path_is_not_followed` (the target stays untouched and nothing raises into the caller).
3. Env limits: `_int_env(name, default, maximum)` clamps `AUTO_SIGNAL_LOG_BACKUP_COUNT` to 20 and `AUTO_SIGNAL_LOG_MAX_BYTES` to 1073741824. Invalid or non-positive values still give the defaults. Test: `test_env_limits_are_clamped` (the existing fallback test still covers invalid values).
4. Huge int: `_small_int` returns the value only for an int with `0 <= v < 2**53` (not bool or float), else None. It is used for `max_tokens` and `think_budget`. Tests: `test_huge_and_odd_ints_do_not_drop_the_record` (`10**5000` still yields one line with null fields; bool, float, negative, `2**53`, str and None give None).
5. Analyzer: names and the `reasoning_effort`/`oc_effort`/`think_type`/`req_class` values are printed with `ascii()`. `sid_hash` and `fm_hash` are accepted only as non-empty `str`. Tests: `test_analyzer_prints_names_escaped` (no raw ESC in stdout), `test_analyzer_survives_valid_json_garbage`.

Code review
6. Analyzer garbage: `load_records` catches `(ValueError, RecursionError)`. Hashes must be `str`. Names go through `ascii()` before `set()`, so list or dict entries can no longer raise. The `req_class` membership test is guarded with `isinstance(..., str)`. Test: `test_analyzer_survives_valid_json_garbage` feeds `{"sid_hash":[1],"fm_hash":[2]}`, a dict `sid_hash`, `body_fields:[[1]]`, mixed `header_names`, a list `req_class`, `[` x 300000 and `{"a":` x 100000, and asserts exit 0 with no traceback and all sections printed.
7. Verdict: the analyzer now prints the rule (constancy >= 95%, shared-session share <= 5%, at least 10 sessions overall and 10 sessions with 2+ main-thread turns), then the measured values with sample sizes (sessions and main-thread turns), then the verdict. Thresholds are constants `MIN_CONSTANCY`, `MAX_SHARED` and `MIN_SESSIONS`. Below the minimum it prints "insufficient sample". Tests: `test_analyzer_verdict_usable_with_enough_clean_sessions` (12 clean sessions x 3 turns -> "usable (thresholds met)"), `test_analyzer_verdict_insufficient_sample` (1 session x 2 turns), `test_analyzer_verdict_not_usable_when_shared` (12 sessions sharing one first message). The existing criterion-12 test now asserts "insufficient sample" instead of "NOT shown to be usable", since its fixture has only 4 sessions. The `(a)`/`(b)` assertions in it are unchanged.

Not done, as instructed: no `AUTO_SIGNAL_LOG_SALT`, hash length unchanged (8 hex, unsalted). The `round-1/` review files are left uncommitted.
