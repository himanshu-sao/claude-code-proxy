STATUS: GREEN

# Build: 003-auto-model-groundwork-t2 (effort handling)

## Files changed
- `src/models/claude.py`: `reasoning_effort` Literal widened to `low|medium|high|xhigh|max`; new `output_config: Optional[Any] = None` (any shape validates).
- `src/conversion/effort_mapper.py`: new `CLIENT_EFFORTS` tuple and pure helper `resolve_client_effort(reasoning_effort, output_config) -> Optional[str]`. Top-level wins; otherwise `output_config.effort` if the config is a dict and `effort` is a string, stripped and lowercased, in `low|medium|high|xhigh|max`; anything else returns `None`. `normalize_effort` is unchanged.
- `src/conversion/request_converter.py`: import plus the `normalize_effort` call only (first argument is now `resolve_client_effort(...)`). Nothing else touched.
- `tests/test_effort_mapper.py`: 38 new tests (model validation, helper precedence/malformed cases, converter end-to-end with a stub model manager and monkeypatched env, non-reasoning model emits no `reasoning_effort`/`extra_body`).

No docs changed (owned by the final docs task). No new env vars.

## Testing
Run from the worktree with `OPENAI_API_KEY=test-key`, using the shared venv python.
- `python -c "import src; print(src.__file__)"` printed `.../.claude/worktrees/003-t2/src/__init__.py` (inside the worktree).
- Baseline before changes: offline subset 36 passed.
- `python -m pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py -q`: 74 passed.
- `python -m black src/ tests/test_effort_mapper.py` and `python -m isort src/ tests/test_effort_mapper.py`: no diff in `src/`; only the new test file was reformatted by black.

## Acceptance criteria
1. Pass: `max` validates, `bogus` raises `ValidationError` (FastAPI renders 422); both tested at model level.
2. Pass: str, list, null, `{}`, `{"effort": 5}`, `{"effort": "bogus"}` all validate.
3. Pass: helper precedence, malformed to `None`, whitespace-only to `None`, `"  HIGH "` to `high`, `xhigh` kept and mapped to `max` by `normalize_effort`.
4. Pass: end-to-end via `convert_claude_to_openai` with a GLM-5 id (max stays `max` there, so the canonical level is visible): output_config max gives `max`; malformed plus `REASONING_EFFORT=low` gives `low`; nothing gives `high`; top-level `low` beats output_config `max`; client effort beats BIG/MIDDLE/SMALL_MODEL_EFFORT (both fields).
5. Pass: a `meta/llama-3.1-70b-instruct` request emits no `reasoning_effort` or `extra_body` for five field combinations.
6. Pass: offline subset green; existing `xhigh -> max` and vocabulary tests unchanged.
7. Pass: black/isort leave no diff in `src/`; no `X | Y` unions or `match` used.

## Deviations
- None from the spec. Note: the 422 for top-level `bogus` is tested at the pydantic level (as the spec says), not through an HTTP call, since `test_endpoints.py` is out of scope.
- `resolve_client_effort` returns the top-level value as-is when truthy (it is already constrained by the Literal); `normalize_effort` handles its case/whitespace as before.

## Blocked / red
Nothing.
