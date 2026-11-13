STATUS: GREEN

# Build — 003-auto-model-groundwork-t4 (context data for two MIDDLE_MODEL ids)

## Files changed
- `model_contexts_cache.json`: appended `mistralai/mistral-large-4-1t-a52b` and `minimaxai/minimax-m3.1-flash`, each `[262144, 32768]`. Existing `indent=2` layout kept. Neither key was present beforehand, so nothing needed correcting in place. The diff only adds lines (the comma after the last existing entry plus the two new keys). The other 12 entries are untouched. The file still has no trailing newline, as before.
- `tests/test_context_manager.py`: new `TestCachedNimLimits` class. A fixture loads the real repo cache from `Path(__file__).resolve().parent.parent / "model_contexts_cache.json"`. It applies the filter from `provider_discovery.py:152-154` (lists of 2, converted to tuples). It uses `monkeypatch.setattr` on `_DISCOVERED_LIMITS` and on `_ENV_OVERRIDES` (`{}`). It never writes the cache and never calls `run_discovery_and_patch`.
- No `src/` change. `MODEL_CONTEXT_LIMITS` and `_BUILTIN_LIMITS` are untouched.

## Tests
Run from the worktree with `OPENAI_API_KEY=test-key` and the shared venv python. `python -c "import src; print(src.__file__)"` printed a path inside the worktree (`.../.claude/worktrees/003-t4/src/__init__.py`).

- `python -m pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py -q` gave `42 passed`.
- The AC1 one-liner (counter hook, 14 unique keys, both values equal `[262144, 32768]`) exited 0.
- `python -m black --check -l 100 tests/test_context_manager.py` and `python -m isort --check tests/test_context_manager.py` both pass.
- Sensitivity check, not committed: I injected a hypothetical earlier `mistralai/mistral-large` entry into the reordered dict. The upper-cased lookup then returned the neighbour's value, so the shadowing test would catch a real shadowing neighbour.

## Acceptance criteria
1. Cache contents: pass, with a diff that is additions only.
2. Exact lookup: pass (`TestCachedNimLimits.test_exact_lookup`, both ids, `!= (32_000, 4_096)`).
3. No neighbour shadowing: pass (`test_no_neighbour_shadowing`, targets moved last, upper-cased ids, and `mistralai/mistral-nemotron` still gives `(128_000, 16_384)`).
4. Env still wins: pass (`test_env_override_still_wins`).
5. Suite and format: pass, as shown above.

## Deviations
None. The spec said `uv run`. I used `python -m` from the shared venv, as the task instructed.

## Blocked or red
Nothing.
