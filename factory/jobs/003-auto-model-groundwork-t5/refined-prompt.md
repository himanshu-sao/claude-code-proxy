# Refined prompt — Sub-job 003-auto-model-groundwork-t5 (task T5 of job 003-auto-model-groundwork)

Sliced from `factory/jobs/003-auto-model-groundwork/refined-prompt.md` (authoritative for anything not repeated here; design decisions live in `factory/jobs/003-auto-model-groundwork/answers.md`).
Out of scope for the whole job: routing logic, stickiness, `/health` counters, overlap warning, removing the duplicate tier lookups (job 004).

## Assumptions (job-wide)
## Assumptions
1. CONFIRMED: `AUTO_MODEL_ALIAS` (default `claude-proxy-auto`) is matched exactly and case-insensitively, after stripping whitespace; an empty value means the default. It is checked before the `gpt-`/`o1-`/`ep-`/`doubao-`/`deepseek-` pass-through and the haiku/sonnet/opus matching (`model_manager.py:15-36`). It returns `(get_active_model("big"), "big")`. Existing aliases are unchanged.
2. CONFIRMED: `AUTO_MODEL_ENABLED` defaults to true. When false, the `/v1/models` entry is removed and the alias behaves as an unknown name. The 4th entry is appended last, its `display_name` has no `-\d{8}`, and the `>= 3` test still passes.
3. CONFIRMED: the `reasoning_effort` Literal (`claude.py:95`, currently `low|medium|high|xhigh`, so `max` returns 422) gains `"max"` only. CONFIRMED: `output_config.effort` is read; nothing reads it today, and it survives in `model_extra`.
4. CONFIRMED (user answer): precedence is top-level `reasoning_effort` > `output_config.effort` > per-tier env > `REASONING_EFFORT` > `high`. A malformed `output_config`/`effort` (wrong type, unknown string) is treated as absent: env defaults apply and the request is never rejected (my addition).
5. PROPOSED: `AUTO_SIGNAL_LOG` defaults off; truthy values are `1/true/yes/on`. Lines are emitted for ALL models so the alias can be compared with the existing aliases. Requests that fail with 422 are never logged.
6. CONFIRMED (user answer): the signal log goes to a separate append-only file `logs/auto_signal.log`, never to `proxy.log` (which `logging.py:56` truncates on each start). It uses a size-capped `RotatingFileHandler`. PROPOSED names and defaults: `AUTO_SIGNAL_LOG_MAX_BYTES` (default 5242880) and `AUTO_SIGNAL_LOG_BACKUP_COUNT` (default 3). The path is fixed, resolved from the project root as `logging.py:28-31` does, and is not configurable. The dedicated logger has `propagate=False`, so signal lines do not also go to the console or `proxy.log`. The handler is attached only when `AUTO_SIGNAL_LOG` is on. It is independent of `LOG_LEVEL`. It creates `logs/` if missing. Any handler/IO/formatting failure is swallowed (DEBUG on the normal logger) and never affects the request. VERIFIED: `.gitignore:179` contains `logs/`, so the file stays untracked. Line prefix stays `AUTOSIGNAL`.
7. UNVERIFIED research (to confirm with the signal log): Claude Code sends effort as `output_config.effort` alongside an `anthropic-beta` header. For an unknown id it sends `thinking: {"type":"adaptive"}`, so a `budget_tokens` value is usually absent. It sends `x-claude-code-session-id` per session, `x-claude-code-agent-id`/`-parent-agent-id` only for subagents, and `x-claude-code-request-class` (`main|subagent|workflow|compaction|auxiliary`) only with `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`. `metadata.user_id` is not documented. Auxiliary calls (titles, summaries) probably reach the alias. `*_SUPPORTED_CAPABILITIES` probably has no effect behind a base-URL gateway.
8. The 3 duplicate tier lookups (`endpoints.py:92`, `:112`, `request_converter.py:25`) stay; job 004 owns them. So the decision reason is NOT logged inside `map_claude_model_to_openai`, which would log it 3 times. Instead, `ModelManager.is_auto_alias()` drives a `reason=auto-placeholder` on the existing request log line in `create_message`.
9. CONFIRMED (user decision): both `mistralai/mistral-large-4-1t-a52b` and `minimaxai/minimax-m3.1-flash` get `[262144, 32768]` in `model_contexts_cache.json`. 262,144 is NVIDIA's published hosted spec, not verified live (vendor figure is about 1M). 32,768 is the repo's own default output cap (precedent c5a0b70), NOT a sourced figure. The cache change and docs must say so.
10. VERIFIED: the response echoes `original_request.model` (`response_converter.py:69, 90, 239`). `get_model_limits` precedence is env > discovered/cache > built-in > `(32_000, 4_096)`. uvicorn runs as a single process (`main.py:103`). `model_contexts_cache.json` is TRACKED, not gitignored (it is in `.git/index` and absent from `.gitignore`, as fc2b7d2 committed it), and it is read from the CWD (`provider_discovery.py:144`). The values go into the cache file only, not into `MODEL_CONTEXT_LIMITS`.
11. The code stays Python 3.9-safe (no runtime `X | Y`, no `match`) and is formatted with black/isort at line-length 100.

## Task T5
- **T5 — wire the log.** Files: `src/api/endpoints.py` only. Pass `request` and `http_request.headers` to the emit function once, near the top of `create_message`, outside any path that can raise into the request. Depends on T1 and T3.

Uses the emit function and record builder from T3 and the alias helper from T1; do not redefine them.

## Goals (relevant to this task)
1. A request with `model: "Claude-Proxy-Auto"` routes to the active BIG model, tier `big`. The request log shows `reason=auto-placeholder` exactly once. The response `model` equals the request value, both streaming and non-streaming. The `.last_model` write still happens.
5. With `AUTO_SIGNAL_LOG` off: no line, no file created, no handler attached. With it on: exactly one line per request is appended to `logs/auto_signal.log` and none to `proxy.log`. A sentinel test (strings in the system prompt, user text, tool name/schema, tool_result, base64 data, header values incl. `x-api-key` and the session id) finds none of them in the line, and all listed fields are present.
6. The file survives a proxy restart (appended, not truncated) and rotates at `AUTO_SIGNAL_LOG_MAX_BYTES`, keeping `AUTO_SIGNAL_LOG_BACKUP_COUNT` backups. A failing log path (unwritable, dir cannot be created) never changes the response status or body of `/v1/messages`.

## Edge cases (relevant to this task)
4. Signal builder inputs: `system` as a list or None, `tools` None, str content, unknown blocks (thinking/redacted_thinking), list `tool_result`, empty `messages`, `metadata` None, adaptive thinking with no budget, missing or duplicate headers, a huge body. The builder never raises; failures are swallowed at DEBUG.

## Depends on
003-auto-model-groundwork-t1, 003-auto-model-groundwork-t3 (must be merged before this sub-job starts its spec stage).

## Orchestrator addendum (added after the T3 approval, 2026-11-13) — binding for T5

Source: `factory/jobs/003-auto-model-groundwork-t3/decision.md`, its security and live reviews, and the T1 approval.
T5 builds on the MERGED T1 and T3 code, not on the base commit. Re-read `src/core/signal_log.py` for the real API
(`emit_signal(request, headers, is_auto_alias)`, `build_signal_record`, `_header_map`).

1. **Call site.** Call `emit_signal` in `create_message` AFTER the request has been validated. A request that fails with 422 never reaches
   the handler, so it is never logged; add a test that proves a 422 request writes no signal line.
2. **Never break a request.** The call must be wrapped so no exception from it can reach the response, and a failing log path
   (unwritable directory, disk full) must not change the status or body of `/v1/messages`. Add a test for exactly that.
3. **Event loop.** `emit_signal` does blocking file I/O. State in the spec which choice you make and why: either offload it
   (`asyncio.get_running_loop().run_in_executor` or similar, without delaying the response) or call it inline and record the trade-off
   (it only runs when `AUTO_SIGNAL_LOG` is on; the T3 live review measured about 0.1 ms for typical bodies and 8 to 21 ms for the worst
   2 MB bodies). If you offload, make sure exceptions in the worker are still swallowed.
4. **Headers.** Pass the real Starlette `Headers` object (`http_request.headers`). The T3 approver verified that `_header_map` handles it,
   including duplicate headers (first value wins); add a TestClient test that sends `x-api-key`, `x-claude-code-session-id` and an
   `anthropic-beta` header and shows the log line carries header NAMES and the session-id hash, but none of the header values.
5. **`is_auto_alias`.** Use `model_manager.is_auto_alias(request.model)` from T1. Do not add a second `reason=` log line: replace nothing in
   T1's `logger.info(... reason=%s)` call and do not duplicate it, or T1's "exactly once" tests fail.
6. **Keep the edit small.** `src/api/endpoints.py` only (plus tests). Do not touch `config.py` or `signal_log.py`; if you need a change there, report BLOCKED
   and say what.
7. **Live review (when local binding is allowed).** It must check: a real FastAPI request with real Claude Code-shaped headers produces one
   line in `logs/auto_signal.log` (use a scratch log path); a failing log path leaves `/v1/messages` unchanged; a 422 request is not logged;
   AUTO_SIGNAL_LOG unset creates no file. The user has so far declined `allowLocalBinding`; if that is still the case, say which of these
   the in-process TestClient tests cover and which stay unverified.
