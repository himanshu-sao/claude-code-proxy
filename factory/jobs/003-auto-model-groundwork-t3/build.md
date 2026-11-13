STATUS: GREEN

# Build report - 003-auto-model-groundwork-t3

## Files changed (all new)
- `src/core/signal_log.py` - `build_signal_record`, `emit_signal`, `_log_path`, `reset_for_tests`. Content-free record, lazy `auto_signal` logger (`propagate=False`, `RotatingFileHandler(mode="a", delay=True)`, double-checked creation under a `threading.Lock`, `handleError` overridden to DEBUG on `proxy`). Env read at call time; imports nothing from `src.core.config`/`logging`.
- `scripts/analyze_signal_log.py` - stdlib-only analyzer (sections per spec, (a) repeat rate and (b) constancy computed separately, main-thread vs all-records, verdict lines). Exit 2 only with no args.
- `tests/test_signal_log.py` - 39 tests covering acceptance criteria 1-13 (tmp_path + monkeypatched `_log_path`; analyzer run via `subprocess` with `sys.executable`).
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
