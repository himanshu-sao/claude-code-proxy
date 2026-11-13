# Answers — Job 003 (auto-model groundwork)

These are the user's confirmed design decisions from the planning session. Treat
everything under "Confirmed" as CONFIRMED. Items marked PROPOSED are not yet
user-confirmed — list them as assumptions for the user to approve.

## Background

The user wants a virtual model, alias `claude-proxy-auto`, that Claude Code can select and
that the proxy routes to one of the three real tiers (BIG_MODEL / MIDDLE_MODEL / SMALL_MODEL).
The work is split in two factory jobs:

- **Job 003 (this job): groundwork + signal logging.** No routing logic.
- **Job 004 (later, out of scope here): the router** — `pick_tier`, escalate-only stickiness,
  context-fit rule, `/health` counters, startup overlap warning. Its refined prompt will be
  written after real traffic has been captured with this job's signal log.

## Confirmed scope of job 003

1. **Alias handling.** Add an exact, case-insensitive match for the alias (env
   `AUTO_MODEL_ALIAS`, default `claude-proxy-auto`) in `ModelManager.map_claude_model_to_openai`
   (`src/core/model_manager.py`), checked BEFORE the `gpt-`/`ep-`/`deepseek-` pass-through and the
   haiku/sonnet/opus substring matching. Until job 004 lands it resolves to the BIG tier exactly as
   an unknown name does today, but explicitly (not by fall-through), and the decision is logged
   with a reason such as `auto-placeholder`. Behaviour of the existing aliases must not change.
2. **`/v1/models` entry.** Add a fourth entry for the alias in `GET /v1/models`
   (`src/api/endpoints.py`). ON by default; `AUTO_MODEL_ENABLED=false` removes the entry and the alias
   then behaves like any unknown name. Existing test only asserts `>= 3` entries; do not break it.
3. **Effort handling.**
   - Widen `ClaudeMessagesRequest.reasoning_effort` (`src/models/claude.py`) so `max` is accepted.
     Today `max` is rejected with a 422, which would fail the whole request if Claude Code sends it.
   - Also read `output_config.effort` (the Anthropic API field; the model already keeps unknown fields
     via `extra="allow"`, nothing reads it today). PROPOSED precedence: top-level `reasoning_effort`
     if present, else `output_config.effort`. Canonical scale unchanged (`low<medium<high<max`,
     `xhigh`→`max`); in-session `/effort` must still always win over env defaults.
4. **Signal log (Phase 0).** Env-gated (PROPOSED name `AUTO_SIGNAL_LOG`, default off), one INFO line per
   `/v1/messages` request, CONTENT-FREE: never system/user/assistant/tool text, never tool schemas,
   never base64 payloads. Purpose: answer these questions from real Claude Code traffic —
   - Which top-level request field NAMES arrive (including extras like `output_config`)?
   - Are `reasoning_effort` / `output_config.effort` / `thinking` (type, `budget_tokens`) present for
     the alias vs the existing aliases?
   - Tool count, `max_tokens`, message count, whether the last message is a tool result.
   - An input-size estimate that INCLUDES the system prompt and tool schemas (the existing
     `estimate_tokens` counts messages only).
   - Does `metadata` carry a per-session id? (log presence/stability only, never raw values)
   - Sticky-key stability: log a short truncated hash of the first user message so that (a) its
     repeat rate across unrelated conversations and (b) its constancy across turns of one
     conversation can be measured. The spec-writer must describe how an offline analysis can tell
     those apart, and security review must judge whether the truncated hash is acceptable.
   - Provide an analysis script under `scripts/` (NOT in the pytest suite) that summarizes the log.
5. **Context-window data fix.** `mistralai/mistral-large-4-1t-a52b` and `minimaxai/minimax-m3.1-flash`
   are configured in MIDDLE_MODEL but missing from `model_contexts_cache.json`, so they fall to the
   32,000-token safe default in `context_manager.get_model_limits`. They must get their real windows.
   The real values are being researched separately by the orchestrator and will be appended to this
   file under "Researched values". Do NOT guess numbers. The spec should treat the values as an input
   and say where they are written (cache file and/or `MODEL_CONTEXT_LIMITS` in `.env.example`).
   The refiner must check whether `model_contexts_cache.json` is tracked or gitignored and say so.
6. **Docs** (project rule — keep in sync): README "Environment Variables" + features, QUICKSTART,
   `.env.example`. Document the new env vars and a "how to select the auto model" section:
   `ANTHROPIC_CUSTOM_MODEL_OPTION=claude-proxy-auto`, `_NAME`, `_DESCRIPTION`, and
   `ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES=effort,thinking,xhigh_effort,max_effort`.
   State that Claude Code does NOT fill the `/model` picker from `/v1/models` unless
   `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1`. State that Claude Code assumes a 200K window for an
   unrecognized model id and compacts there; users should set `CLAUDE_CODE_MAX_CONTEXT_TOKENS` (or
   `/autocompact`). Note the proxy runs a single uvicorn process (relevant to job 004's in-memory state).

## Explicitly OUT of scope (job 004)

Tier-picking logic, stickiness map, context-fit routing, `/health` counters, startup same-model
warning, removing the three duplicate tier lookups (endpoints.py:92, :112 and
request_converter.py:25). Do not refactor those here beyond what items 1–4 strictly need.

## Constraints for task decomposition

- Make tasks as FILE-DISJOINT as possible and list the files each task touches. The orchestrator will
  run disjoint tasks in parallel in separate worktrees and must serialize tasks that share a file.
  Likely shared files: `src/api/endpoints.py`, `src/core/config.py`, README/`.env.example`.
  Put all documentation in its own final task that depends on the others.
- Project conventions: config only from env vars; every new env var documented in `.env.example`
  and README; `scripts/` is not part of pytest; offline tests =
  `uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py`;
  format with `uv run black src/ && uv run isort src/`.
- Facts verified in the planning session (re-verify before relying on them): single uvicorn process
  (`src/main.py:103`); `get_model_limits` precedence env > discovered > built-in > 32K default;
  the response converter echoes `original_request.model`, so the alias is returned unchanged.
- Treat "proceed with your assumptions" as granted for anything not listed above, EXCEPT the PROPOSED
  items, which must be surfaced as assumptions for the user.

## Researched values

### Claude Code request behavior (researched from official docs by a subagent; NOT user-confirmed)

Source: code.claude.com docs (llm-gateway-protocol, model-config, env-vars, sub-agents). Some pages were
truncated when read, so "not documented" means "not found in what was read". Treat all of this as
assumptions to be verified by the Phase 0 signal log, not as facts.

1. **Effort field.** Documented: effort travels in the body as `output_config.effort` (paired with an
   `anthropic-beta` header). Top-level `reasoning_effort` is NOT documented anywhere that was read.
   Consequence: today the proxy reads only `reasoning_effort` (`src/models/claude.py:95`,
   `request_converter.py:126`), so `/effort` may not reach it at all. Reading `output_config.effort` is
   therefore more than a nicety; the spec must say which field wins and must log both.
   Values a user can pick: `low|medium|high|xhigh|max`. Exact wire strings: not documented.
   If the upstream rejects effort, Claude Code retries once without it and omits it for the rest of the run.
2. **Unrecognized model ids (gateway aliases).** Documented: for the Anthropic Messages format, Claude Code
   sends "everything current Claude models accept", including adaptive reasoning and effort, and treats the
   alias as a current model.
3. **`_SUPPORTED_CAPABILITIES` behind a gateway.** Documented: the `ANTHROPIC_DEFAULT_*_MODEL_SUPPORTED_CAPABILITIES`
   variables "have no effect behind an `ANTHROPIC_BASE_URL` gateway". Whether
   `ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES` is honored there is NOT documented (inferred: no).
   Consequence: the README must not promise that declaring capabilities enables effort/thinking; document
   `_NAME` and `_DESCRIPTION` (documented to work behind a gateway) and mark capabilities as unverified.
4. **Thinking.** Documented: adaptive `{"type":"adaptive"}` is sent by default for unrecognized ids; a fixed
   `budget_tokens` appears only on other paths. Consequence: with adaptive thinking on every request, the
   "thinking budget" signal is effectively absent, so job 004's BIG signal would be effort-only. The existing
   model class (`ClaudeThinkingConfig`) already accepts `adaptive`. On a 400 about `thinking.type`, Claude Code
   retries with the other type.
5. **Session identity.** Documented: header `x-claude-code-session-id` (unique per Claude Code session) is
   sent; `metadata.user_id` is NOT documented. Subagent headers: `x-claude-code-agent-id`,
   `x-claude-code-parent-agent-id` (present only for subagent requests).
   Optional hint headers (need `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`, v2.1.273+): `x-claude-code-request-class`
   (`main|subagent|workflow|compaction|auxiliary`), `x-claude-code-prompt-id`, `x-claude-code-compaction`,
   `x-claude-code-agent-type`. Whether the session-id header is sent by default behind a custom base URL
   is not stated.
6. **Which requests reach the alias.** Documented: behind a custom gateway with a gateway token, background
   tasks run on the MAIN model (our alias) unless `ANTHROPIC_DEFAULT_HAIKU_MODEL` pins one; with an Anthropic
   Console key they use the default Haiku model. Title/summary classification is only partly documented.
   Consequence: with the alias selected, auxiliary calls (titles, classifiers, summaries) probably DO reach
   the alias, and `x-claude-code-request-class: auxiliary` could identify them. Subagents use the main
   model by default.

### Implications for this job (the spec must address them)

- The signal log must record header NAMES (never values) in addition to body field names, and presence of
  `x-claude-code-session-id`, `x-claude-code-request-class` and the agent-id headers, plus whether the
  session id is stable across turns (via a short truncated hash of the header value, never the raw value).
- The log is the only way to learn the real effort field; it must log presence/values of both
  `reasoning_effort` and `output_config.effort` (values are enum strings, safe to log), and thinking type.
- Open for the user (job 004 and the sticky key): the header `x-claude-code-session-id` may be a better
  conversation key than a first-message hash. Phase 0 must collect enough to compare the two.

### Context windows

Researched from primary pages (build.nvidia.com model pages, Hugging Face cards and configs, vendor docs).
Web search was unavailable to the researcher; the build.nvidia.com `/modelcard` pages returned no content.
Nothing has been written to `model_contexts_cache.json` yet. Neither model is currently in it.

| Model | NVIDIA hosted "Specifications" line | Vendor / weights figure | Max output |
|---|---|---|---|
| `mistralai/mistral-large-4-1t-a52b` | 262,144 | 1,048,576 (HF card, `max_position_embeddings`, vendor docs) | not stated anywhere |
| `minimaxai/minimax-m3.1-flash` | 262,144 | 1,000,000 (vendor docs, HF card); weights `max_position_embeddings` 1,048,576 | not stated anywhere |

- NVIDIA's own pages are internally inconsistent: the Specifications line says 262,144, while the Input/Output
  sections of the same page repeat the 1M figure (for MiniMax: "Input Context Length (ISL): 1,000,000"). No page says
  whether 262,144 is an enforced limit of the hosted endpoint.
- No primary source gives a numeric max-output for either model. Precedent: commit `c5a0b70` used 32768 for the
  output side of two other models; that is the repo's own choice, not a sourced figure.
- **DECIDED by the user (CONFIRMED):** store the NVIDIA hosted figure 262,144 as the context window and 32768 as
  the max output for BOTH models, i.e. `[262144, 32768]` each:
  - `mistralai/mistral-large-4-1t-a52b` -> `[262144, 32768]`
  - `minimaxai/minimax-m3.1-flash` -> `[262144, 32768]`
  The 32768 output cap is the repo's own default (precedent: commit `c5a0b70`), NOT a sourced figure; the docs and
  the cache change must say so. The 262,144 window is NVIDIA's published hosted spec; it was not verified live.

## User answers to the refiner's open questions (CONFIRMED, 2026-11-13)

1. **Effort precedence:** top-level `reasoning_effort` wins over `output_config.effort`; then per-tier env >
   `REASONING_EFFORT` > built-in `high`. (Assumption 4 in the refined prompt becomes CONFIRMED.)
2. **Signal-log destination:** a separate append-only file `logs/auto_signal.log`, NOT the existing
   `proxy.log` (which `src/core/logging.py:56` truncates on every start). It must survive restarts. The spec
   must define a size cap with rotation (RotatingFileHandler is fine) via env vars documented in `.env.example` and
   README, must create the `logs/` directory if missing, and must never let a logging failure break a request.
   `logs/` must stay gitignored (verify). The `AUTOSIGNAL` line prefix can stay for grep-ability.

## Notes for T5 and job 004 (from the T3 security review, 2026-11-13)

- T5 must call `emit_signal` AFTER request validation, wrapped so it cannot raise into the request. The file write
  is blocking I/O on the event loop; offload it (for example `run_in_executor`) if it can be done without
  complicating the request path, otherwise state the trade-off in the T5 spec.
- The signal-log hashes are 8 hex (32 bits), unsalted, kept for this capture only. Job 004 needs at least 64 bits for a
  real conversation key, and that key must live in memory, not in a persistent file.

## Additional notes for job 004 (from the T3 approval, 2026-11-13)

- The signal-log hashes (`sid_hash`, `fm_hash`) are 8 hex characters, unsalted, for the Phase 0 capture only. They must NOT be reused as the routing or
  stickiness key. Job 004's conversation key must be at least 64 bits and held in memory, never written to a persistent file.
- Job 004 should add a test that round-trips a real `emit_signal` hash through the analyzer's `_is_hash` (`scripts/analyze_signal_log.py`), so a future change to the hash
  length or format cannot silently zero the analyzer's key comparison (the analyzer accepts only `[0-9a-f]{1,64}`).
- Process lesson from job 003: when sub-jobs touch the same request model, run a combined-tree merge check BEFORE the individual reviews close. T2 declared
  `output_config` as a field and T3 read it only from `model_extra`; no single-branch review could see it, and it cost an extra review round.
- Optional hardening noted by the approvers (not part of job 003): guard the discovery `update()` in `provider_discovery.py` so provider metadata cannot
  overwrite curated cache entries; sanitize the client-supplied model name in the request log line (pre-existing log-injection surface).
