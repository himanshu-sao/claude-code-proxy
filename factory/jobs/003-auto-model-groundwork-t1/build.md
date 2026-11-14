STATUS: GREEN

# Build: 003-auto-model-groundwork-t1 (T1, auto alias and `/v1/models` entry)

Branch `factory/003-auto-model-groundwork-t1`. Commit hash: see the final message and `git log` (a commit cannot contain its own hash).

## Files changed
- `src/core/config.py`: added module-level `DEFAULT_AUTO_MODEL_ALIAS` and `parse_auto_enabled(raw)`. `Config.__init__` now sets `auto_model_alias` (env `AUTO_MODEL_ALIAS`, stripped, empty or whitespace falls back to `claude-proxy-auto`, original casing kept) and `auto_model_enabled` (unset is true; false after strip and lowercase for `false`, `0`, `no`, `off`, `""`; anything else is true).
- `src/core/model_manager.py`: added `ModelManager.is_auto_alias(name)`. It is true only when enabled and `name.strip().lower() == alias.lower()`, and false for non-strings. `map_claude_model_to_openai` checks it first and returns `(get_active_model("big"), "big")`. No other branch was changed.
- `src/api/endpoints.py`, three small localized edits, `create_message` otherwise untouched.
  - `list_models` appends the alias entry last when `config.auto_model_enabled` is true. Its `display_name` is `"Auto (routes to big tier)"`, with fixed `created_at` and `created` values.
  - The `list_models` docstring was updated.
  - `reason=%s` was added to the existing request `logger.info` call, with `auto-placeholder` or `tier-map`. No new log call was added, and the duplicate mapping and `_write_last_model` logic were left untouched.
- `tests/test_model_manager.py` (new): a fake-config `ModelManager` test covering casing and whitespace, a custom alias replacing the default, `gpt-`/`deepseek-`/`o1-`/`ep-`/`sonnet` alias names taking the auto branch, existing mappings unchanged and `is_auto_alias` false, BIG fallback following, the disabled fall-through, and the `parse_auto_enabled` value tables.
- `tests/test_endpoints.py` (tests appended only): the alias is last in `/v1/models` (4 entries), the alias is hidden when disabled (3 entries), and the log line appears exactly once with `reason=auto-placeholder` and `tier=big`. Further tests cover `reason=tier-map` for an opus alias and for a disabled alias, `.last_model` written once with `("big", active big)`, and the response `model` echoing `Claude-Proxy-Auto` for both non-streaming JSON and streaming `message_start`. The upstream client and `_write_last_model` are stubbed with `monkeypatch`.

No docs or `.env.example` changes, as the spec leaves them to the docs task.

## Testing (run from the worktree, `OPENAI_API_KEY=test-key`, shared venv python)
- `python -c "import src; print(src.__file__)"` printed `.../.claude/worktrees/003-t1/src/__init__.py`, which is inside the worktree.
- `python -m pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py tests/test_model_manager.py -q -p no:warnings` gave 81 passed.
- `python -m black --check src/ && python -m isort --check src/` was clean. Black and isort were also run on the two test files.
- `tests/test_main.py` and `tests/test_compat_endpoints.py` have 8 failures with httpx `ConnectError`. These are live-integration tests that need a proxy on :8082, are not in the offline subset, and are unrelated to this change.
- Manual env check: `AUTO_MODEL_ALIAS="  " AUTO_MODEL_ENABLED=Off` gives `('claude-proxy-auto', False)`, and `AUTO_MODEL_ALIAS=" My-Auto "` gives `('My-Auto', True)`.

## Acceptance criteria
1. Pass (`test_default_alias_case_and_whitespace`).
2. Pass. The empty and whitespace alias is covered by the manual env check and the `Config` code path. The `my-opus-auto` case is in `test_custom_alias_replaces_default`.
3. Pass (`test_custom_alias_beats_passthrough_and_substring_rules`).
4. Pass (`test_existing_mappings_unchanged`).
5. Pass (`test_alias_follows_big_fallback`).
6. Pass (`test_list_models_includes_auto_alias_last`, plus the unchanged `test_list_models`).
7. Pass (`test_list_models_hides_auto_alias_when_disabled`, `test_disabled_alias_*`, and the `parse_auto_enabled` tables for `False`, `0`, `""` and unset).
8. Pass (`test_auto_alias_request_log_and_last_model`, `test_tier_map_request_logs_tier_map_reason`, `test_disabled_alias_logs_tier_map`). Each asserts exactly one `reason=` line.
9. Pass (the two echo tests, and the `.last_model` assertion in the log test and in the streaming test).
10. Pass (81 passed, black and isort clean).

## Deviations and notes
- No deviations from the spec.
- The `""` handling for `AUTO_MODEL_ENABLED` (an empty string means disabled) follows the spec's stated reading. The docs task should state it.
- `parse_auto_enabled` is a public module-level helper in `config.py` so the parser can be tested directly. This is a small addition and not a behavior change.
- The `-> tuple[str, str]` annotation in `model_manager.py` was already there. I did not touch it.
