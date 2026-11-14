SIZE WARNING: this task touches 5 files (3 source, 2 test) and has 10 acceptance criteria, over the 3-file / 5-criterion gate. The split is deliberate. The source edits are about 30 lines in total, and the tests are in separate files from the source. Docs and `.env.example` are left to the docs task, so no env var is documented here.

# Spec: T1, auto alias and `/v1/models` entry

## Goal
Add a virtual model alias (`AUTO_MODEL_ALIAS`, default `claude-proxy-auto`) that `ModelManager.map_claude_model_to_openai` resolves explicitly to `(get_active_model("big"), "big")`. The match is exact and case-insensitive, and it runs before every other rule. `GET /v1/models` lists the alias as a 4th entry unless `AUTO_MODEL_ENABLED` is false. The existing request log line gains `reason=`. There is no routing logic, which belongs to job 004.

## Approach
- `src/core/config.py`: in `Config.__init__`, add two attributes next to the other env reads.
  - `auto_model_alias`: `os.environ.get("AUTO_MODEL_ALIAS", "")`, stripped. Empty means `claude-proxy-auto`. The original casing is kept for the `/v1/models` id.
  - `auto_model_enabled`: unset is true. A set value is false if, after strip and lowercase, it is one of `false`, `0`, `no`, `off` or `""`. Any other value is true. The `""` case is my reading of the refined prompt's edge case, and the docs task should state it.
  - Tests flip these attributes with `monkeypatch.setattr`, not env vars, because `config` is built at import time.
- `src/core/model_manager.py`: add `is_auto_alias(self, name) -> bool`, which is true only when `auto_model_enabled` is true and `name.strip().lower() == auto_model_alias.lower()`. In `map_claude_model_to_openai`, put `if self.is_auto_alias(claude_model): return self.config.get_active_model("big"), "big"` as the first check, before the `gpt-`/`o1-` check. Do not change any other branch. Keep the code Python 3.9-safe.
- `src/api/endpoints.py`: three small localized edits, because T5 later edits `create_message` too.
  - In `list_models`, append the alias entry last when `config.auto_model_enabled` is true. Use `id=config.auto_model_alias` and `display_name="Auto (routes to big tier)"`. The display name has no `-\d{8}`. Use fixed `created_at` and `created` values, and `owned_by` comes from the existing comprehension.
  - Update the `list_models` docstring: it no longer says "exactly one alias per tier", and it should mention the optional auto alias.
  - Add `reason=%s` to the existing `logger.info("Request [%s] ...")` call, with the value `"auto-placeholder"` if `model_manager.is_auto_alias(request.model)` else `"tier-map"`. Add no new log call, and leave the duplicate mapping at line 112 and the `_write_last_model` logic untouched.
- Tests: new `tests/test_model_manager.py` builds `ModelManager` with a small fake config object. Add tests only to `tests/test_endpoints.py`. Use `caplog` and `monkeypatch`, and stub the upstream client for the log, echo and `.last_model` checks (`_write_last_model` can be patched).

## Acceptance criteria
1. With default config, `map_claude_model_to_openai(x)` returns `(<active big model>, "big")` for `x` in `claude-proxy-auto`, `Claude-Proxy-Auto` and `  CLAUDE-PROXY-AUTO  ` (leading and trailing whitespace).
2. With `AUTO_MODEL_ALIAS` set to `""` or whitespace, the alias is `claude-proxy-auto`. With `my-opus-auto`, that name takes the auto branch, so `big` is returned with `is_auto_alias` true, and `claude-proxy-auto` is no longer special.
3. Custom aliases such as `gpt-auto` and `deepseek-auto` also take the auto branch, not the pass-through. The result is the BIG model with tier `big`, not `(name, "unknown")`.
4. Existing mappings are unchanged, and `is_auto_alias` is false for all of them. `claude-3-5-haiku-*` maps to `small`, `*sonnet*` to `middle`, `*opus*` to `big`, `gpt-4o` and `deepseek-v3` pass through with tier `unknown`, and an unknown name falls to `big`.
5. When `_active_big_idx > 0` (BIG fallback active), the alias returns the fallback model. Test with a fake config or by setting `config._active_big_idx` and restoring it.
6. `GET /v1/models` includes the alias as the last entry by default. The `display_name` has no `-\d{8}`, the entry has all the usual fields, and `test_list_models` still passes unchanged (>= 3 entries).
7. With `auto_model_enabled=False`, set from the `False`, `0` and `""` env-style values through a parser test, the alias is absent from `/v1/models`. `is_auto_alias` is false, and mapping the alias name falls through to the unknown-name path with no auto branch. With any of those values, the unset default is true.
8. A `POST /v1/messages` request with `model: "Claude-Proxy-Auto"` writes the request log line exactly once, and that line contains `reason=auto-placeholder` and `tier=big`. A request with `claude-3-opus-20240229` logs `reason=tier-map`. `caplog` records no second line containing `reason=` per request.
9. For the same alias request, the non-streaming JSON response and the streaming `message_start` both carry `model` equal to the request value as sent (`Claude-Proxy-Auto`). `_write_last_model("big", <active big model>)` is called once.
10. `uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py tests/test_model_manager.py` passes offline, and `uv run black --check src/ && uv run isort --check src/` is clean.
