APPROVE

Sub-job 003-auto-model-groundwork-t1, build commit 7d0b4cc (base 1d5a0e4). I am approving it because the in-process tests cover every behaviour the blocked live review would have checked. The only thing missing is the HTTP and process layer, which the user explicitly accepted.

## Rationale
- Acceptance criteria 1-10 are met. I read the diff and the tests, and I did not rely only on the PASS verdicts. The source change is about 30 lines. `map_claude_model_to_openai` gains one early return, with no other branch touched. `Config` gains `auto_model_alias` and `auto_model_enabled`. `endpoints.py` gains one extra `%s` in the existing log call plus the `list_models` block and docstring.
- Tests, re-run by me in the worktree. `src.__file__` resolves inside `.claude/worktrees/003-t1`. The offline subset (effort_mapper, endpoints, context_manager, model_manager) gives 81 passed. `black --check -l 100 src/` and `isort --check --profile black -l 100 src/` are clean. The working tree has only untracked job files. HEAD is 7d0b4cc.
- Security PASS and code PASS are both deserved. The alias match is plain equality with no regex. The BIG model always comes from config, never from client input. The new log value is one of two constants. The `/v1/models` entry exposes no internal model names. Auth is unchanged. The environment-dependence of some tests is a minor note, and `.env` has no `AUTO_*` keys.
- The orchestrator reports that T1+T2+T3+T4 merged in a scratch tree gave 190 passed with black and isort clean. I did not re-run that merge and I accept the figure as reported.
- Config policy is respected. The settings come from env vars only, and the defaults are in code.
- T5 conflict risk is low. The `create_message` edit is a single `%s` and one ternary argument inside the existing `logger.info` call (`endpoints.py:96-103`). The duplicate mapping and the `_write_last_model` block are untouched. T5 should replace that ternary and not add a second `reason=` log line. T5's own logging should not emit a second line containing `reason=`, or the "exactly once" tests will fail.
- The T6 docs deferral is recorded. `spec.md` line 1 and `build.md` ("No docs or `.env.example` changes, as the spec leaves them to the docs task") both say so. T6's `refined-prompt.md` lists `AUTO_MODEL_ALIAS` and `AUTO_MODEL_ENABLED` in its scope. The project rule requires the vars in `.env.example` and the README, so T6 must not be skipped before merge to main.

## In-process coverage versus the blocked live checks
| Live check | In-process coverage | Verdict |
|---|---|---|
| Alias routes to BIG, `tier=big`, `reason=auto-placeholder` logged once | `test_auto_alias_request_log_and_last_model` posts `Claude-Proxy-Auto` through the real FastAPI app with a stubbed upstream. It asserts exactly one `reason=` log line containing `reason=auto-placeholder` and `tier=big` | Covered |
| `reason=tier-map` for existing aliases and for a disabled alias | `test_tier_map_request_logs_tier_map_reason`, `test_disabled_alias_logs_tier_map` | Covered |
| `/v1/models` lists the alias last, with the usual fields | `test_list_models_includes_auto_alias_last` checks the id, type, object, owned_by, created fields, no `-\d{8}` in `display_name`, and 4 entries. The unchanged `test_list_models` still passes | Covered |
| `AUTO_MODEL_ENABLED=false` removes the alias | The `/v1/models` test gives 3 entries. The mapping tests cover fall-through. `parse_auto_enabled` is tested for `False`, `0`, `""`, whitespace and unset | Covered for the in-process state; see the restart gap below |
| Response `model` echoes the request value | Non-streaming JSON and the streaming `message_start` SSE event both assert `Claude-Proxy-Auto`. `.last_model` is written once with `("big", active big)` | Covered |
| BIG fallback followed | `test_alias_follows_big_fallback` | Covered |

Named gaps in the in-process coverage. None is blocking.
1. `AUTO_MODEL_ALIAS=""` or whitespace falling back to the default is not tested through `Config`. Only the manual env check in build.md covers it. I confirmed it myself: `AUTO_MODEL_ALIAS="  "` gives `claude-proxy-auto`. It is simple, single-line code.
2. The streaming test checks the echo and `.last_model`. It does not check the `reason=` log line for a streaming request. The log call sits before the stream/non-stream split, so the same line is emitted.
3. Some endpoint tests assume no `AUTO_*` keys in the developer's environment or `.env`. This is currently true. If it ever bites, set both attributes with `monkeypatch.setattr` in those tests.
4. Nothing exercises the real env-to-`Config` path at process start for `AUTO_MODEL_ENABLED`. The unit tests flip attributes with `monkeypatch`. The parser itself is tested directly, and I ran a manual env check.

## Unverified
These live checks did not run. The sandbox refused to bind port 8799, and the user declined a rerun with `allowLocalBinding` ("No, proceed"). The board keeps `reviews.api = BLOCKED`.
- A real uvicorn process serving `POST /v1/messages` with `model: "Claude-Proxy-Auto"`, routing to BIG, with `reason=auto-placeholder` once in the real log output (not caplog).
- A real HTTP `GET /v1/models` listing the alias in order, including JSON serialisation over the wire.
- A restart with `AUTO_MODEL_ENABLED=false` in the process environment, confirming the alias disappears and behaves as an unknown name.
- The real `.env` and `load_dotenv(override=True)` interaction. The api-tester inferred that a `.env` above the worktree may override exported vars. That inference is unconfirmed. It matters only for how a future live run is set up.
- Streaming against a real upstream, as opposed to the stub.

## Carry forward to T6 (docs: `README.md`, `QUICKSTART.md`, `.env.example`)
- Document `AUTO_MODEL_ALIAS` and `AUTO_MODEL_ENABLED` in both `.env.example` and the README "Environment Variables" section.
- `AUTO_MODEL_ALIAS`: default `claude-proxy-auto`. It is matched exactly and case-insensitively after whitespace stripping. An empty or whitespace value means the default. It is checked before the `gpt-`/`o1-`/`ep-`/`doubao-`/`deepseek-` pass-through and the haiku/sonnet/opus matching. A custom alias such as `gpt-auto` or `my-opus-auto` therefore takes the auto branch. The id shown in `/v1/models` keeps the casing that was set.
- `AUTO_MODEL_ENABLED`: default true, and unset means true. The exact false values are `false`, `0`, `no`, `off` and the empty string, compared after strip and lowercase.
  - A blank `AUTO_MODEL_ENABLED=` line DISABLES the alias.
  - Any other value is true. This includes a typo such as `flase`, which fails open and leaves the alias enabled. I verified this. State it plainly.
  - When false, the `/v1/models` entry is removed and the alias is treated like any unknown name. That falls through to BIG by the unknown-name default, but with `reason=tier-map`.
- Until job 004 the alias always resolves to the active BIG model, and follows a BIG fallback.
- The alias shows up in `/v1/models` as a 4th entry, appended last, with `display_name` "Auto (routes to big tier)".
- Request log lines now end with `reason=auto-placeholder` or `reason=tier-map`.
- The T1 `.env.example` entries should mention that tests assume no `AUTO_*` keys in the developer's environment (optional).
