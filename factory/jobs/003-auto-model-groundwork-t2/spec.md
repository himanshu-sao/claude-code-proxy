SIZE WARNING: this task touches 4 files (the gate is 3) and has 7 acceptance criteria (the gate is 5). The edge cases in the refined prompt each need a concrete check, so the count is kept. The work is still one small, self-contained effort change. Split only if the reviewer wants it.

## Goal

Make effort handling accept what Claude Code actually sends. The top-level `reasoning_effort` field gains `max`, so `max` returns 200 instead of 422. The proxy also reads the documented `output_config.effort` field, which is currently ignored. The precedence is top-level `reasoning_effort` > `output_config.effort` > per-tier `*_MODEL_EFFORT` > `REASONING_EFFORT` > built-in `high`. Malformed `output_config` is treated as absent and never rejects a request. Top-level `reasoning_effort: "bogus"` still returns 422. No new env vars.

## Approach

- `src/models/claude.py`: widen the `reasoning_effort` Literal (line 95) to `low|medium|high|xhigh|max`. Add `output_config: Optional[Any] = None` so the field is typed but can never fail validation. Any shape is accepted.
- `src/conversion/effort_mapper.py`: add a pure helper, e.g. `resolve_client_effort(reasoning_effort, output_config) -> Optional[str]`. Take primitives, not the pydantic model, to avoid an import cycle. It returns top-level `reasoning_effort` if set, else `output_config.effort` if it is a dict whose `effort` is a string. The string is stripped and lowercased, and must be one of `low|medium|high|xhigh|max`. Anything else returns `None`. This filter is required: `normalize_effort("bogus", env)` returns `high`, which would silently bypass the env default. `normalize_effort` itself stays unchanged. `max` is already canonical and `xhigh` already maps to `max`.
- `src/conversion/request_converter.py` (lines 125-127 only): pass `resolve_client_effort(claude_request.reasoning_effort, claude_request.output_config)` as the first argument to the existing `normalize_effort` call. Leave the rest of the block and the `model_manager` lookup untouched.
- `tests/test_effort_mapper.py`: add unit tests for the helper, model validation, and the converter. Reuse the `_fresh_config` / monkeypatch pattern for env. For the converter, use a stub `model_manager` whose `map_claude_model_to_openai` returns a fixed `(model, tier)`.
- No changes to `test_endpoints.py`. Docs are owned by the final docs task. Both the effort-mapping table in README and the `effort_mapper.py` module docstring can be updated there.

## Acceptance criteria

1. `ClaudeMessagesRequest(reasoning_effort="max", ...)` validates. `reasoning_effort="bogus"` raises a pydantic `ValidationError`, which the endpoint turns into a 422. A test covers both.
2. `output_config` of any shape validates without error: a str, a list, `null`, `{}`, `{"effort": 5}`, `{"effort": "bogus"}`.
3. Helper precedence: top-level `low` with `output_config.effort="max"` gives `low`. With top-level absent and `output_config.effort="max"`, it gives `max`. With both absent, it gives `None`. Malformed `output_config` (str, list, null, `{}`, `effort` of 5, `"bogus"`, whitespace-only) gives `None`. Case and whitespace are normalized, so `"  HIGH "` gives `high`, and `"xhigh"` gives `xhigh`, which `normalize_effort` maps to `max`.
4. Converter end-to-end (stub model manager, env via monkeypatch): with `output_config.effort="max"` and no top-level field, the canonical level is `max`. With malformed `output_config` and `REASONING_EFFORT=low`, the result is `low`. With no client effort and no env, the result is `high`. With top-level `low` and `output_config` `max`, the result is `low`. Client effort beats `BIG/MIDDLE/SMALL_MODEL_EFFORT`.
5. For a non-reasoning model (for example a plain Llama-style id), `convert_claude_to_openai` emits no `reasoning_effort` and no `extra_body` for any combination of the two effort fields.
6. Regression: `uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py` passes. The existing `xhigh -> max` and per-provider vocabulary tests are unchanged and still pass.
7. `uv run black src/ && uv run isort src/` leaves no diff in the touched files. The code stays Python 3.9-safe, so no `X | Y` unions and no `match`.
