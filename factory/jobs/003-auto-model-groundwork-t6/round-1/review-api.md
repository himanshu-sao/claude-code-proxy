VERDICT: PASS

Executed the T6 documentation (README.md, QUICKSTART.md, .env.example, effort_mapper docstrings) in-process, without a server and without binding a port or starting uvicorn. Every runnable claim I checked matched observed behaviour, apart from three minor wording nits (N1-N3 below) that do not block a merge. Nothing is BLOCKED; the items that need a real server or a real Claude Code are listed under UNVERIFIED.

Setup and substitutions
- Worktree: `~/Work/src/extra/himanshu-sao/claude-code-proxy/.claude/worktrees/003-t6`, HEAD = docs commit 0e58d00 + build notes; diff base 11b8f2a.
- Substituted the venv python `~/Work/src/extra/himanshu-sao/claude-code-proxy/.venv/bin/python` (3.14.0) with `python -m pytest ...` for the docs' `uv run pytest ...`, and for `python3`. `uv` itself was not run. `OPENAI_API_KEY=test-key`. Scratch files only under `$TMPDIR` (= `/tmp/claude-501/t6/...`). `logs/` in the worktree contains only `proxy.log` before and after; the real `logs/auto_signal.log` and the real `model_contexts_cache.json` were never created or written (sha1 of the cache compared before/after).
- `python -c "import src; print(src.__file__)"` resolves inside the worktree.
- The parent checkout's `.env` is picked up by `load_dotenv(override=True)` (it has no `AUTO_*` keys); I overrode tier models on the config object where a check needed them.

1. Shell commands in the docs
- `python -m pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py tests/test_model_manager.py tests/test_signal_log.py -q -p no:cacheprovider` -> `214 passed` (matches README/QUICKSTART "214").
- `python -m pytest tests/ --ignore=tests/test_main.py ...` -> `239 passed` (matches "239").
- Old three-file command (effort_mapper, endpoints, context_manager) -> `111 passed` (matches the stale-count claim). `tests/test_main.py` hard-codes `http://localhost:8082/v1/messages` (live proxy needed), as the docs say; not run.
- Env-var parity loop from the spec (`for v in $(grep -rhoE 'AUTO_[A-Z_]+' src | sort -u) ...`) printed no MISSING; the set is exactly AUTO_MODEL_ALIAS, AUTO_MODEL_ENABLED, AUTO_SIGNAL_LOG, AUTO_SIGNAL_LOG_BACKUP_COUNT, AUTO_SIGNAL_LOG_MAX_BYTES.
- README greps: `logs/auto_signal.log` 5, `analyze_signal_log.py` 2, `0600` 1, `95%` 2, `5%` 2, `insufficient sample` 1, `restart` 7, `ANTHROPIC_CUSTOM_MODEL_OPTION` 5, `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY` 2; both new headings and `### Context windows` present.
- `python -m black --check -l 100 src/` -> 17 files unchanged; isort --check clean. AST comparison of `effort_mapper.py` at 11b8f2a vs HEAD with docstrings stripped: identical. `git diff --stat 11b8f2a HEAD -- src CLAUDE.md factory/project.md` lists only `src/conversion/effort_mapper.py` (docstring lines).
- `grep -inE 'rout(e|es|ing)'` over README/QUICKSTART/.env.example: every hit near the alias says BIG tier / no routing until job 004; the only literal "routes" is the quoted display name. Remaining hits are unrelated effort/`endpoints.py` wording.

Analyzer (`python3 scripts/analyze_signal_log.py logs/auto_signal.log*`), reproduced in scratch dirs with real files written by `src.core.signal_log.emit_signal` (`_log_path` patched, 3 turns per session, `ClaudeMessagesRequest`):
- 12 sessions, each with a stable distinct first message: `Verdict: fm_hash is usable (thresholds met)`; constancy 100.0% (12 of 12), shared 0.0% (0 of 12).
- 12 sessions, half sharing one prompt: `Verdict: fm_hash is NOT shown to be usable (thresholds not met)`; shared-session share 50.0% (6 of 12).
- 5 sessions: `insufficient sample (5 sessions, 5 with 2+ main-thread turns; need at least 10 of each)`.
- Boundary: 9 sessions -> insufficient sample; 10 sessions -> usable.
- Rotated set (MAX_BYTES=2000, BACKUP_COUNT=3 gave `auto_signal.log`, `.1`, `.2`, `.3`; the glob expanded to all four, `files: 4`). With MAX_BYTES=8000 the glob gave 3 files and `files: 3, records: 36`, verdict usable.
- Same input under `/usr/bin/python3` (3.9.6, what bare `python3` resolves to in this shell), `/opt/homebrew/bin/python3` (3.14.5) and the venv 3.14.0: identical verdicts, exit 0 in all three. So `python3 scripts/analyze_signal_log.py ...` works on 3.9.6 and 3.14.
- Exit codes: no file argument -> exit 2, usage on stderr, nothing on stdout (also with 3.9.6). Empty file -> exit 0, `files: 1, records: 0`, `Verdict: fm_hash is undetermined (no records with both hashes)`. Missing path -> exit 0 with `warning: cannot read missing.log: [Errno 2] ...` on stderr and the same "undetermined" summary. Garbage file (non-JSON AUTOSIGNAL lines, a JSON list, invalid UTF-8) -> exit 0, `skipped invalid AUTOSIGNAL lines: 3`, "undetermined". Mixed empty+missing+garbage+valid -> exit 0, `files: 4, records: 36, skipped: 3`, usable. This matches "skips lines it cannot parse, exits 2 only when no file is given" and the "undetermined" wording.

2. Env vars read through the real code path (`src.core.config.Config`, `src.core.signal_log`)
- AUTO_MODEL_ENABLED: unset, `true`, `TRUE`, `1`, `yes`, `on`, `flase`, `disabled`, `2` -> enabled. `false`, `False`, `FALSE`, `0`, `no`, `No`, `off`, `OFF`, `` (blank), `   `, ` false ` -> disabled. Matches "only false/0/no/off or blank disable; a typo like flase leaves it on".
- AUTO_MODEL_ALIAS: unset, blank and whitespace -> `claude-proxy-auto`; `Custom-Auto` and `  GPT-Auto  ` -> original casing, stripped.
- AUTO_SIGNAL_LOG: `1`, `true`, `TRUE`, `Yes`, `yes`, `on`, `ON`, ` on ` -> on. unset, `0`, `false`, blank, `2`, `enabled`, `y`, `t`, `flase`, `off`, `no` -> off. Matches fail-closed.
- AUTO_SIGNAL_LOG_MAX_BYTES: unset/blank/`abc`/`0`/`-5`/`1.5`/`1e3` -> 5242880; `1`, `1000`, `  2048  ` accepted; `1073741824` -> 1073741824; `1073741825` and `99999999999999` -> 1073741824.
- AUTO_SIGNAL_LOG_BACKUP_COUNT: unset/blank/`abc`/`0`/`-1` -> 3; `1`, `3`, `20` accepted; `21` and `1000` -> 20.
- "Switch per request, limits once": with a live handler, setting `AUTO_SIGNAL_LOG=0` mid-run stopped writes with no restart; setting MAX_BYTES after the first record left `handler.maxBytes == 5242880`, `backupCount == 3`. Matches the corrected README wording.
- `.env` overrides the shell: `AUTO_MODEL_ENABLED=false` exported, `.env` line `AUTO_MODEL_ENABLED="true"`, `load_dotenv(override=True)` -> enabled True. Matches the README note.

3. Effort behaviour through the real app (`fastapi.testclient.TestClient`, stubbed upstream, opus -> BIG tier set to `z-ai/glm-5.3`; observed upstream `reasoning_effort`)
- no effort -> 200, `high`. Top-level `max` -> 200, `max`; `xhigh` -> `max`; `low` -> `low`. Top-level `HIGH` -> 422; `bogus` -> 422. (On `main`, the Literal lacked `max`, confirming "used to return 422".)
- `output_config.effort` `" HIGH "` -> 200, `high`; `" MAX "` -> `max`; `xhigh` -> `max`; `low` -> `low`.
- Malformed `output_config` (string, list, `effort: 5`, `effort: "bogus"`, `null`) -> 200, ignored (`high` default). With `REASONING_EFFORT=low`, `oc bogus` -> `low` (env default still applies), `oc max` -> `max`.
- Both given: top `low` + oc `max` -> `low`; top `max` + oc `low` -> `max`; top `high` + oc `low` -> `high`. Env: `BIG_MODEL_EFFORT=max` over `REASONING_EFFORT=low` -> `max` with no client effort; client `oc low` still wins -> `low`. Matches the five-step precedence.
- README effort table via `resolve_effort(normalize_effort(level))`: GLM-5.x low/high/high/max/max for low/medium/high/xhigh/max (medium -> high). gpt-oss low/medium/high/high/high. deepseek-v4.1-flash low/high/high/high/high (so "`low/high` (medium and max become high)" is right and the old "low/medium/high" was wrong). Nemotron (nano and ultra): low -> `enable_thinking: False`; medium/high -> thinking on, `medium_effort: True` only for the `ultra` name; xhigh/max -> thinking on, no `medium_effort`. kimi-k2-thinking and qwen3-*-thinking -> nothing. All table cells match.

4. /v1/models and Model Mapping
- `GET /v1/models` default -> 200, 4 entries, 4th = `claude-proxy-auto`, `display_name` `Auto (routes to big tier)`. `AUTO_MODEL_ALIAS=Custom-Auto` -> 4th id `Custom-Auto` (casing kept). `AUTO_MODEL_ENABLED=false` and blank -> 3 entries. `flase` -> 4 entries.
- Mapping, enabled: `claude-proxy-auto`, `Claude-Proxy-Auto`, `  claude-proxy-auto ` all -> active BIG, tier `big`. Failover: with BIG list `[primary-big, fallback-big]` and idx 1 the alias follows to `fallback-big`.
- Request log line: auto -> `reason=auto-placeholder`; opus -> `reason=tier-map`; disabled default alias -> `reason=tier-map`, BIG.
- Disabled-alias paragraph: default `claude-proxy-auto` -> BIG/`big`; `gpt-auto` (disabled) -> `('gpt-auto', 'unknown')` pass-through; `my-opus-auto` (disabled) -> BIG; `x-haiku-auto` -> SMALL; `x-sonnet-auto` -> MIDDLE. With the alias enabled, `gpt-auto` -> BIG (alias checked first). All as documented.

Signal log behaviour via TestClient (stub upstream, `_log_path` in scratch):
- Off by default: 0 lines, file not created. On: a non-stream auto request and a streaming `gpt-4o` request each append one line (2 lines). 401 (bad key), 422 (missing messages) and 422 (bogus effort) append nothing. Unwritable log path (parent is a regular file) -> `/v1/messages` still 200 with the upstream text.
- Privacy: the strings `SECRET-PROMPT-TEXT`, `hello`, the session id and the bearer token do not appear in the file. `sid_hash` equals `sha256("sid:"+session)[:8]` and `fm_hash` equals `sha256("msg:"+normalised text)[:8]` (8 hex).
- File mode 0600 on a pre-existing 0755 `logs/` dir, directory mode left 0755. `O_NOFOLLOW` present; a symlink at the log path was not followed (target unchanged, response still 200). A module-created directory is 0700 under umask 022 (the README says not to assume 0700 in a running proxy because `logging.py` creates `logs/` first; not exercised without the real startup).
- Inline cost, measured here: ~0.18 ms for a 41 KB body, ~7.7 ms for a 2 MB body (README: 0.12 ms and 6-10 ms; same order, machine-dependent).

5. Cache and context windows (scratch copies only, cwd switched to `$TMPDIR` dirs; `run_discovery_and_patch` with `discover_provider_limits` stubbed)
- Cache values: both `mistralai/mistral-large-4-1t-a52b` and `minimaxai/minimax-m3.1-flash` are `[262144, 32768]` in the tracked file; resolved limits `(262144, 32768)`, zero upstream calls when all configured models are present, cache file unchanged.
- Read from the current directory: with cwd lacking the file, both models resolve to `(32000, 4096)`, discovery runs, and a new `model_contexts_cache.json` is written in that cwd.
- Missing model (`brand-new/model-x`): one upstream discovery call, the scratch cache gained `[32000, 4096]` for it and no existing entry changed. A discovery result for a curated model replaced it in the scratch cache file (`[123456, 1111]`), confirming "discovery output can overwrite curated entries".
- `MODEL_CONTEXT_LIMITS=mistral-large-4:1000:500` beat the discovered `(262144, 32768)` -> `(1000, 500)`; default `(32000, 4096)` confirmed. "Loaded only at startup" was read from `src/main.py` (`@app.on_event("startup")`), not exercised.

6. `.env.example` block
- Copied the new block to a scratch `.env`, uncommented the five `AUTO_*` lines, parsed with python-dotenv: values `claude-proxy-auto`, `true`, `false`, `5242880`, `3`; inline `#` comments after the quoted values do not leak into the values; Config shows alias `claude-proxy-auto`, enabled True, signal log off, max 5242880, backups 3. A shell `AUTO_MODEL_ENABLED=false` was overridden by the `.env` `true`. Edited to `My-Auto` / `flase` / `on` / `99999999999` / `50`: alias `My-Auto`, enabled True (typo stays on), log on, max 1073741824, backups 20. Blank `AUTO_MODEL_ENABLED=` -> disabled, blank `AUTO_SIGNAL_LOG=` -> off, blank MAX_BYTES -> default.

Minor wording nits (do not block a merge; the documented operational behaviour is correct)
- N1. README "File mode" bullet says the mode is "re-applied with `fchmod` ... (the umask can only make it stricter)". Observed: because of `fchmod`, the file is 0600 under umask 022, 077, 277 and 377 alike, so the umask cannot make it stricter than 0600 on POSIX. Suggest dropping the parenthetical.
- N2. The documented `python3 scripts/analyze_signal_log.py logs/auto_signal.log*` fails under zsh with `no matches found` (exit 1, before python runs) if no log file exists yet; bash passes the literal pattern and the script warns on stderr but exits 0. Not covered by the "exits 2 only when no file is given" statement, so not wrong.
- N3. Undocumented side effect: with no `model_contexts_cache.json` in the cwd the proxy creates one there (the README mentions rewriting the tracked file and reading from the cwd only).

UNVERIFIED (needs a real server or a real Claude Code; none run)
- Any live HTTP run (uvicorn, real sockets, `start.sh`, `curl`), including the startup event that triggers discovery, real client disconnects, shutdown, concurrency/latency under load, and the on-disk modes of a `logs/` directory created by `src/core/logging.py` in a running proxy.
- The Claude Code settings in "Selecting the auto model in Claude Code" (`ANTHROPIC_CUSTOM_MODEL_OPTION`, `_NAME`, `_DESCRIPTION`, `_SUPPORTED_CAPABILITIES`, `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`, `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `CLAUDE_CODE_GATEWAY_HINT_HEADERS`, `/autocompact`, the 200K assumption) and the real Claude Code request shape (`output_config.effort`, headers, adaptive thinking); the README itself says these are unchecked.
- `uv run ...` command forms (venv `python -m pytest` used instead), the full live `uv run pytest tests/` including `tests/test_main.py`, Windows/no-`O_NOFOLLOW` platforms, multi-worker rotation, the 262,144 / 32,768 figures, and the 95%/5% thresholds' validity.

Worktree state: `git status --short` shows only the untracked `factory/jobs/003-auto-model-groundwork-t6/round-1/` directory (this file plus the existing review-security.md); no tracked file modified.
