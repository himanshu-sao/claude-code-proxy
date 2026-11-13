# Refined prompt — Sub-job 003-auto-model-groundwork-t6 (task T6 of job 003-auto-model-groundwork)

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

## Task T6
- **T6 — docs (last; depends on T1-T5).** Files: `README.md`, `QUICKSTART.md`, `.env.example`. Document `AUTO_MODEL_ALIAS`, `AUTO_MODEL_ENABLED`, `AUTO_SIGNAL_LOG`, `AUTO_SIGNAL_LOG_MAX_BYTES`, `AUTO_SIGNAL_LOG_BACKUP_COUNT` in both `.env.example` and the README env-vars section. State that the signal file is `logs/auto_signal.log`, append-only, survives restarts, rotates at the cap, is content-free, and stays gitignored (`logs/`). Also document the effort-field handling and a "select the auto model" section: `ANTHROPIC_CUSTOM_MODEL_OPTION=claude-proxy-auto` plus `_NAME`/`_DESCRIPTION`. Mark `_SUPPORTED_CAPABILITIES=effort,thinking,xhigh_effort,max_effort` as UNVERIFIED behind a gateway, without promising that it enables effort or thinking. Also document `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` for the picker, the 200K default (`CLAUDE_CODE_MAX_CONTEXT_TOKENS` / `/autocompact`), optional `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`, the single uvicorn process, how to run `scripts/analyze_signal_log.py` (including its rotated-file handling), and that the two new context windows are the NVIDIA hosted spec with a repo-default 32,768 output cap.

Documents the behaviour delivered by T1-T5; read the merged code and the T1-T5 specs/builds so names and defaults match exactly.

## Goals (relevant to this task)
9. The offline suite (`uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py`) and the new tests pass, and black/isort are clean. Every new env var appears in both `.env.example` and the README. `git status` shows `logs/` stays untracked.

## Edge cases (relevant to this task)
8. Doc variable names and defaults match the code exactly.

## Depends on
003-auto-model-groundwork-t1, 003-auto-model-groundwork-t2, 003-auto-model-groundwork-t3, 003-auto-model-groundwork-t4, 003-auto-model-groundwork-t5 (must be merged before this sub-job starts its spec stage).

## Orchestrator addendum (added after the T1-T4 approvals, 2026-11-13) — binding for T6

These facts come from the approvers' "Carry forward" sections (`decision.md` in the T1, T2, T3 and T4 job folders) and the reviews. Verify each against the
merged code before writing it down; document what the code does, not what this list says.

**AUTO_MODEL_ALIAS / AUTO_MODEL_ENABLED (T1).** Alias default `claude-proxy-auto`, matched exactly, case-insensitively, after whitespace stripping; an
empty or whitespace value means the default; checked before the `gpt-`/`o1-`/`ep-`/`deepseek-` pass-through, so a custom alias like `gpt-auto` takes
the auto branch. `AUTO_MODEL_ENABLED` defaults to true; the exact false values are `false`, `0`, `no`, `off` and the empty string (after strip and
lowercase). A blank `AUTO_MODEL_ENABLED=` line DISABLES the alias; any other value, including a typo like `flase`, leaves it ENABLED (fails open) —
say so plainly. When disabled the `/v1/models` entry is removed and the alias is an unknown name (BIG by the unknown-name default, `reason=tier-map`).
Until job 004 the alias resolves to the active BIG model and follows a BIG fallback. It is the 4th `/v1/models` entry, `display_name` "Auto (routes to big tier)".
Request log lines end with `reason=auto-placeholder` or `reason=tier-map`. Tests assume no `AUTO_*` keys in the developer's environment.

**Effort (T2).** `reasoning_effort` accepts `low|medium|high|xhigh|max`; `output_config.effort` is also read; precedence top-level `reasoning_effort` >
`output_config.effort` > per-tier `*_MODEL_EFFORT` > `REASONING_EFFORT` > `high`; `xhigh` maps to `max`; a malformed `output_config` is ignored and never
rejected; a top-level unknown value like `bogus` still returns 422. Update the README effort-mapping table and features, and the `effort_mapper.py` module
and `normalize_effort` docstrings (they do not mention `output_config`); check QUICKSTART's effort mentions. Optional cheap test: a TestClient test that
POST `/v1/messages` with `reasoning_effort: "bogus"` returns 422 (put it in whichever task next touches `tests/test_endpoints.py`).

**Signal log (T3), five env vars.** `AUTO_SIGNAL_LOG` (default off; truthy `1/true/yes/on`), `AUTO_SIGNAL_LOG_MAX_BYTES` (default 5242880, clamped to at most
1 GiB = 1073741824), `AUTO_SIGNAL_LOG_BACKUP_COUNT` (default 3, clamped to at most 20); invalid, empty or non-positive values fall back to the defaults 5242880
and 3, values above the clamp are clamped. Document: file `logs/auto_signal.log`, append-only, survives restarts, rotates at the cap, separate from
`proxy.log` (which is truncated each start). File mode 0600 (created with `O_NOFOLLOW` where the platform has it, so a symlink at the path is not followed).
The directory is created 0700 only when the module creates it; an existing `logs/` is left alone, and missing parent directories get default modes.
Rotation is safe for the single uvicorn process only; multiple workers are unsupported. Privacy statement, accurate and not over-claiming: the record holds
no message, system, tool or header VALUES and no base64; it holds identifier-shaped NAMES (body fields, header names, `output_config` and `metadata` keys,
the model name; `[A-Za-z0-9_.:/-]{1,64}`, anything else logged as `other`), counts, enum values, and two 8-hex unsalted hashes (session id and first user
message). Short or templated prompts can be confirmed by someone who hashes a guess and can read the file, so keep the file local and delete it after the
capture. How to run it: `python scripts/analyze_signal_log.py logs/auto_signal.log*` (rotated files included). Verdict rule: `fm_hash` is usable as a
conversation key only if main-thread constancy >= 95%, shared-session share <= 5%, with at least 10 sessions overall and 10 sessions with 2+ main-thread
turns; below that the analyzer says "insufficient sample". The 95%/5% thresholds are the builder's own choice (the spec gave no numbers).

**Context windows (T4).** Both `mistralai/mistral-large-4-1t-a52b` and `minimaxai/minimax-m3.1-flash` are `[262144, 32768]` in `model_contexts_cache.json`.
Do NOT call 262,144 verified or 32,768 sourced: 262,144 is NVIDIA's published hosted spec (vendors claim about 1M), not verified live; 32,768 is the repo's own
default output cap with no source (precedent: commit c5a0b70). Mention that the proxy reads the cache from the current directory, loads it only at startup
(restart after changing it), rewrites the tracked file when a configured model is missing from it, and that provider discovery output can overwrite curated entries.

**Selecting the auto model in Claude Code** (from the research; mark capability behavior as UNVERIFIED): `ANTHROPIC_CUSTOM_MODEL_OPTION=claude-proxy-auto` plus
`_NAME` and `_DESCRIPTION`; the `_SUPPORTED_CAPABILITIES` variable is documented to have no effect behind a gateway for the `ANTHROPIC_DEFAULT_*` family and is
undocumented for the custom option, so do not promise it enables effort or thinking. Claude Code only fills `/model` from `/v1/models` when
`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`. It assumes a 200K window for an unrecognized id: set `CLAUDE_CODE_MAX_CONTEXT_TOKENS` or `/autocompact`.
Optional hint headers need `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`. Do not describe `claude-proxy-auto` as doing any routing yet: it always resolves to the BIG tier.
