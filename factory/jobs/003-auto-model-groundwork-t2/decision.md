APPROVE

Sub-job 003-auto-model-groundwork-t2 (effort: accept `max`, read `output_config.effort`). Build commit 251fc85, base 1d5a0e4.

## Rationale
- All 7 acceptance criteria hold. I read the diff: `claude.py` widens the Literal with `max` and adds `output_config: Optional[Any]`. `effort_mapper.py` adds the pure helper `resolve_client_effort`. `request_converter.py` changes only the import and the first argument of `normalize_effort`. No env vars, no I/O, and no change to `normalize_effort`.
- Reproduced: `src.__file__` is inside the worktree. The offline suite (`test_effort_mapper.py`, `test_endpoints.py`, `test_context_manager.py`) gives 74 passed. `black --check -l 100` is clean on `src/` and the new test file. isort (black profile, line length 100) is clean.
- The security PASS and code PASS are deserved. The helper only does `isinstance` checks, one `.get`, and a membership test against a fixed tuple, so hostile `output_config` cannot raise or select a level. The raw `output_config` is never forwarded upstream or logged. The whitelist filter prevents the `normalize_effort("bogus")` to `high` fallback from bypassing the env default.
- Precedence is confirmed in the code. `resolve_client_effort` returns the top-level value first, then `output_config.effort`. `normalize_effort` (unchanged) takes that as the client value ahead of the per-tier env (`get_effort_default(tier)`), then `REASONING_EFFORT`, then `high`. A malformed or unknown `output_config` becomes `None`, so it falls through to the env instead of being coerced to `high`. In-session `/effort` therefore still always wins over env defaults.
- Orchestrator evidence: the T1+T2+T3+T4 scratch merge passed 190 offline tests, and the end-to-end check showed the proxy and the signal log agree on effort for four request shapes. I did not re-run that merge. It matches the code I read.
- Docs deferral to T6 is recorded in `spec.md` ("Docs are owned by the final docs task"), `build.md` ("No docs changed (owned by the final docs task)") and the code review (nit c). Every new env var rule is moot here because there are none.

## Coverage of the blocked live review (in-process vs live)
Covered by in-process tests that exercise the real code:
- `max` accepted: `test_reasoning_effort_max_validates` and `test_converter_top_level_max_is_accepted`.
- `output_config`-only effort: `test_converter_reads_output_config_effort`. It runs the real `convert_claude_to_openai` and the real `normalize_effort`, with a stub model manager and a fresh `Config` built from monkeypatched env.
- Top-level wins when the fields conflict: `test_converter_top_level_beats_output_config`.
- Malformed `output_config` never rejects: `test_output_config_of_any_shape_validates` (8 shapes), plus the converter fallback-to-env loop over all of them.
- Client effort beats all three per-tier env vars, through both carrier fields.
- Non-reasoning model gets no envelope: 5 field combinations, no `reasoning_effort` and no `extra_body`.
- Upstream envelope per model family: the converter tests assert the emitted `reasoning_effort` on a GLM-5.1 id. The per-family vocabulary (deepseek-v4 nudges, gpt-oss caps, Nemotron `chat_template_kwargs`) is covered by the existing unchanged `resolve_effort` tests. T2 does not alter that mapping, only the input to it.

Gap named: the 422 for top-level `reasoning_effort: "bogus"` is tested only at the pydantic level. That is adequate for the behaviour but not proven through the route in the committed tests. I closed it ad hoc, in-process and without a server. I ran `TestClient(app).post("/v1/messages", json={..., "reasoning_effort": "bogus"})` and it returned 422 with `literal_error` at `loc=["body","reasoning_effort"]`. The same call with `max` got past validation (it failed later at the upstream connection, which the sandbox denied). That ad hoc check is not committed. A TestClient test closes the gap cleanly with no server and no upstream. Validation fails before any upstream call, and `ANTHROPIC_API_KEY` unset means `validate_api_key` returns early. The fixture already exists, because `tests/test_endpoints.py` builds `TestClient(app)`. A 200 for `max` via TestClient would need a mocked upstream client, so it is not a cheap add. It is also low risk, since `max` passing validation is the same Literal that the pydantic test covers.

This is a small, framework-guaranteed gap. I verified it by hand, so I am not escalating. I recommend a one-test follow-up (see Carry forward).

## Unverified
These live checks did NOT run (the sandbox refused to bind a local port). The user declined a rerun and chose to proceed. The board keeps `reviews.api = BLOCKED`.
- A live scratch proxy on :8799 returning HTTP 200 (not 422) for `reasoning_effort: "max"`.
- A fake upstream on :8798 receiving the effort envelope in the actual outgoing request body for each model family, over the real HTTP path (`UpstreamClient`, retries, streaming).
- `output_config`-only effort, conflicting fields, and malformed `output_config` over real HTTP, including the SSE/streaming path.
- Real Claude Code traffic: that Claude Code actually sends `output_config.effort` (still the research assumption 7 in the refined prompt). The T3 signal log is meant to confirm this.
- The 422 for `bogus` via a committed test. It was checked ad hoc only, as described above.

## Carry forward
For T6 (docs task):
- README "effort mapping" table and features: document that `reasoning_effort` accepts `low|medium|high|xhigh|max`, that `output_config.effort` is read, and the precedence top-level `reasoning_effort` > `output_config.effort` > per-tier `*_MODEL_EFFORT` > `REASONING_EFFORT` > `high`. State that a malformed `output_config` is ignored and never rejected, and that top-level `bogus` still returns 422.
- Update the `effort_mapper.py` module docstring and the `normalize_effort` docstring (lines about 94-95), which still do not mention `output_config`. Also update the ClaudeCode `/effort` note in QUICKSTART if effort is mentioned there.
- `.env.example`: no new vars from T2, so nothing to add for this task.
- Optional, cheap test: add a TestClient test in `tests/test_endpoints.py` (or `test_effort_mapper.py`) that POSTs `/v1/messages` with `reasoning_effort: "bogus"` and asserts 422. Do it in whichever task next touches `test_endpoints.py`, because T2 deliberately did not edit it.
- Re-check the live behaviours in the Unverified list once local port binding is available, or when real traffic is captured with the T3 signal log.
