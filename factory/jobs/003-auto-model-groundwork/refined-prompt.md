# Refined prompt — Job 003: auto-model groundwork (no routing logic)

## Open questions (need user input)
None. Both earlier questions are answered (effort precedence, signal-log destination). The names and defaults of the two rotation env vars (assumption 6) are my proposal and are listed there.

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

## Refined prompt
Single job, tasks T1-T6. Out of scope (job 004): routing, stickiness, `/health` counters, overlap warning, removing the duplicate lookups.

- **T1 — alias + `/v1/models`.** Files: `src/core/config.py`, `src/core/model_manager.py`, `src/api/endpoints.py` (models entry, docstring, `reason=` on the existing log line), new `tests/test_model_manager.py`, `tests/test_endpoints.py` (add tests only). Independent.
- **T2 — effort.** Files: `src/models/claude.py`, `src/conversion/effort_mapper.py` (helper that extracts the client effort from both fields), `src/conversion/request_converter.py` (lines 125-127 only), `tests/test_effort_mapper.py`. Independent.
- **T3 — signal module + script.** Files: new `src/core/signal_log.py`, new `tests/test_signal_log.py`, new `scripts/analyze_signal_log.py` (not in pytest). Independent. The module has:
  - a pure record builder over the request and the header mapping;
  - a lazily created dedicated logger `auto_signal` with a `RotatingFileHandler` on `logs/auto_signal.log` (`mode="a"`, `encoding="utf-8"`, the cap and backup count from the env vars, `propagate=False`, `logs/` created with `os.makedirs(exist_ok=True)`);
  - an emit function that does nothing when disabled and wraps everything (handler setup, build, write) in try/except.

  It reads `os.environ` directly, so `config.py` is untouched. It does not import from T2 or `src.core.logging`. Tests use `tmp_path` and never write to the real `logs/`: handler attached only when enabled, append across logger re-initialisation, rotation at a tiny cap, missing directory created, unwritable path swallowed, one line per call.
- **T4 — context data.** Files: `model_contexts_cache.json`, `tests/test_context_manager.py`. Independent. Add both ids with exactly `[262144, 32768]`; leave other entries untouched. The test asserts both keys exist with those values, and that the limits are not the 32,000 default.
- **T5 — wire the log.** Files: `src/api/endpoints.py` only. Pass `request` and `http_request.headers` to the emit function once, near the top of `create_message`, outside any path that can raise into the request. Depends on T1 and T3.
- **T6 — docs (last; depends on T1-T5).** Files: `README.md`, `QUICKSTART.md`, `.env.example`. Document `AUTO_MODEL_ALIAS`, `AUTO_MODEL_ENABLED`, `AUTO_SIGNAL_LOG`, `AUTO_SIGNAL_LOG_MAX_BYTES`, `AUTO_SIGNAL_LOG_BACKUP_COUNT` in both `.env.example` and the README env-vars section. State that the signal file is `logs/auto_signal.log`, append-only, survives restarts, rotates at the cap, is content-free, and stays gitignored (`logs/`). Also document the effort-field handling and a "select the auto model" section: `ANTHROPIC_CUSTOM_MODEL_OPTION=claude-proxy-auto` plus `_NAME`/`_DESCRIPTION`. Mark `_SUPPORTED_CAPABILITIES=effort,thinking,xhigh_effort,max_effort` as UNVERIFIED behind a gateway, without promising that it enables effort or thinking. Also document `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` for the picker, the 200K default (`CLAUDE_CODE_MAX_CONTEXT_TOKENS` / `/autocompact`), optional `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`, the single uvicorn process, how to run `scripts/analyze_signal_log.py` (including its rotated-file handling), and that the two new context windows are the NVIDIA hosted spec with a repo-default 32,768 output cap.

**Signal record (content-free).** One single-line record per request, prefixed `AUTOSIGNAL`. It contains:
- sorted body field NAMES (fields set plus extras)
- sorted lowercased header NAMES (never values; so `authorization`/`x-api-key` values never appear)
- `model`, `is_auto_alias`, `stream`, `max_tokens`
- message count, `last_is_tool_result`, tool count, image count
- raw `reasoning_effort`; `output_config` key names and `effort` (logged only if it is in the known enum set, else `other`)
- `thinking.type` and `budget_tokens`
- the `anthropic-beta` presence flag
- session-id presence plus a truncated hash
- agent-id/parent-agent-id presence flags
- request-class (enum-filtered)
- `metadata` key names plus a presence flag (no values)
- an input-token estimate (chars//4) that covers system text, message text, tool_use input, tool_result text and `json.dumps(tool schemas)`, excluding base64
- a truncated hash of the first user message

It never contains message, system or tool text, tool names or schemas, or base64 data. The file is plain append-only text with a timestamp on each line (own formatter), because it now outlives the process.
- The analysis must compare two candidate conversation keys: the session-id hash and the first-message hash. (a) Repeat rate: count how many distinct session ids share one first-message hash. Injected `<system-reminder>`/CLAUDE.md blocks may cause collisions; the spec-writer decides what is hashed. (b) Constancy: the first-message hash must stay fixed across the turns of one session id. The analysis also reports the auxiliary/subagent share, using request-class and agent-id. The script takes one or more files (so `auto_signal.log`, `.1`, `.2` can be combined) and skips non-`AUTOSIGNAL` lines.
- The security review must judge the hash length (e.g. 8 hex), salted vs unsalted, the dictionary-guess risk, and that a persistent file now holds these hashes and header names.

## Goals
1. A request with `model: "Claude-Proxy-Auto"` routes to the active BIG model, tier `big`. The request log shows `reason=auto-placeholder` exactly once. The response `model` equals the request value, both streaming and non-streaming. The `.last_model` write still happens.
2. haiku/sonnet/opus/`gpt-`/`deepseek-` mappings are unchanged. A custom alias `my-opus-auto` takes the auto branch.
3. `/v1/models` lists the alias by default and drops it when `AUTO_MODEL_ENABLED=false`. In that case, mapping falls through with no auto reason.
4. `reasoning_effort:"max"` now returns 200 instead of 422. With only `output_config:{"effort":"max"}`, the canonical effort is `max`. When both fields are present, top-level `reasoning_effort` wins. With neither, the env defaults apply. `xhigh` still maps to `max`, and the client value still beats `*_MODEL_EFFORT`/`REASONING_EFFORT`.
5. With `AUTO_SIGNAL_LOG` off: no line, no file created, no handler attached. With it on: exactly one line per request is appended to `logs/auto_signal.log` and none to `proxy.log`. A sentinel test (strings in the system prompt, user text, tool name/schema, tool_result, base64 data, header values incl. `x-api-key` and the session id) finds none of them in the line, and all listed fields are present.
6. The file survives a proxy restart (appended, not truncated) and rotates at `AUTO_SIGNAL_LOG_MAX_BYTES`, keeping `AUTO_SIGNAL_LOG_BACKUP_COUNT` backups. A failing log path (unwritable, dir cannot be created) never changes the response status or body of `/v1/messages`.
7. `scripts/analyze_signal_log.py <file...>` prints:
   - field-name and header-name frequencies
   - effort and thinking presence, per alias vs non-alias
   - size, tool and `max_tokens` stats
   - the tool-result share
   - the session-key comparison

   It exits 0 on an empty or garbage log.
8. After the cache loads, `get_model_limits("mistralai/mistral-large-4-1t-a52b")` and `get_model_limits("minimaxai/minimax-m3.1-flash")` each return `(262144, 32768)`, never `(32000, 4096)`.
9. The offline suite (`uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py`) and the new tests pass, and black/isort are clean. Every new env var appears in both `.env.example` and the README. `git status` shows `logs/` stays untracked.

## Edge cases
1. Alias casing and whitespace; empty `AUTO_MODEL_ALIAS`; a custom alias containing `opus`/`gpt-`/`deepseek-`; `AUTO_MODEL_ENABLED` set to `False`/`0`/`""`.
2. A BIG fallback is active (`_active_big_idx > 0`): the alias follows it.
3. `output_config` is a str, list, null or `{}`; `effort` is `5` or `"bogus"`: all ignored with no 4xx/5xx. Top-level `reasoning_effort:"bogus"` still returns 422. Conflicting fields (top-level `low` vs `output_config` `max`): top-level wins. Non-reasoning models still get no envelope.
4. Signal builder inputs: `system` as a list or None, `tools` None, str content, unknown blocks (thinking/redacted_thinking), list `tool_result`, empty `messages`, `metadata` None, adaptive thinking with no budget, missing or duplicate headers, a huge body. The builder never raises; failures are swallowed at DEBUG.
5. File handler: `logs/` missing at first write; file not writable or disk full; invalid or non-positive `AUTO_SIGNAL_LOG_MAX_BYTES`/`BACKUP_COUNT` (fall back to the defaults, never crash at import); two requests racing on first-handler creation (no duplicate handlers, so no duplicated lines); `AUTO_SIGNAL_LOG` toggled only at startup (no hot reload). Rotation under the single uvicorn process is safe (a multi-worker deployment is out of scope and is noted in the docs). `LOG_LEVEL=WARNING` does not suppress the signal file, since it is independent. Lines have no embedded newlines.
6. The hash is skipped when there is no user message or no session header. Unsalted hashes are stable across restarts, a trade-off for the security review.
7. The cache already holds a stale `(32000, 4096)` for the two ids: correct the entries, do not duplicate them. `MODEL_CONTEXT_LIMITS` still wins. Substring matching in discovered limits must not pick up a neighbour's limits (e.g. `mistralai/mistral-nemotron` vs `mistral-large-4`).
8. Doc variable names and defaults match the code exactly.
