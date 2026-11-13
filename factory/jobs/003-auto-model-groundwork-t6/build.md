STATUS: GREEN

# Build notes: 003-auto-model-groundwork-t6 (docs)

Branch `factory/003-auto-model-groundwork-t6`. Docs commit `0e58d00`; this file is committed on top of it (see final message for the head SHA).

## Files changed
- `.env.example`: new "virtual auto model + signal log" block (after the effort block, before "Server settings") with the five `AUTO_*` variables, defaults, clamps, fail-open/fail-closed and blank-value notes; precedence line under the effort block; note beside `MODEL_CONTEXT_LIMITS` that two NVIDIA windows live in `model_contexts_cache.json`.
- `README.md`: Features (effort bullet amended, auto-alias bullet, signal-log bullet); `.env` override/restart note; Reasoning Effort paragraph (precedence, deepseek wording fixed); new "Auto Model" and "Auto Model Signal Log" env groups; Model Mapping alias row, no-routing and disabled-alias nuance; new `### Context windows`; `### Selecting the auto model in Claude Code`; `### Signal log (Phase 0 capture)` (incl. "What is NOT verified"); effort table (`xhigh` / `max` row, Nemotron cells) and notes; `/v1/models` endpoint row; Testing section; Project Structure.
- `QUICKSTART.md`: alias row in the mapping table, short "Optional: auto model" section, effort levels list, the five-file offline command and the `tests/test_main.py` live caveat.
- `src/conversion/effort_mapper.py`: the module docstring and the `normalize_effort` docstring only.
- `factory/jobs/003-auto-model-groundwork-t6/build.md`: this file.
- Not touched: `CLAUDE.md`, `factory/project.md`, `factory/board.json`, any other job's files, tests.

## Commands run and results (shared venv python, cwd = worktree, `OPENAI_API_KEY=test-key`)
- `python -c "import src; print(src.__file__)"` -> `.../.claude/worktrees/003-t6/src/__init__.py` (inside the worktree).
- `python -m pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py tests/test_model_manager.py tests/test_signal_log.py -q -p no:cacheprovider` -> `214 passed, 40 warnings`.
- `python -m pytest tests/ --ignore=tests/test_main.py -q -p no:cacheprovider` -> `239 passed`.
- Old three-file command -> `111 passed`.
- Env-var parity loop from criterion 1 -> printed nothing; `grep -rhoE 'AUTO_[A-Z_]+' src | sort -u` gives exactly `AUTO_MODEL_ALIAS`, `AUTO_MODEL_ENABLED`, `AUTO_SIGNAL_LOG`, `AUTO_SIGNAL_LOG_BACKUP_COUNT`, `AUTO_SIGNAL_LOG_MAX_BYTES`.
- AST check (old `git show HEAD:src/conversion/effort_mapper.py` vs new, docstrings stripped, `ast.dump`) -> `AST identical: True`. `git diff -U0 -- src/` shows only docstring lines.
- `python -m black --check -l 100 src/` -> `17 files would be left unchanged`; `python -m isort --check src/` -> clean (no output; pyproject sets line length 100).
- `git diff --stat` before commit: `.env.example`, `QUICKSTART.md`, `README.md`, `src/conversion/effort_mapper.py` only.
- `grep -inE 'rout(e|es|ing)' README.md QUICKSTART.md .env.example` reviewed: every hit near the alias says BIG tier / no routing until job 004, except the quoted `/v1/models` display name `Auto (routes to big tier)` (README, explained as literal text) and unrelated existing wording ("The proxy routes each level to the correct parameter", "route to each model's native envelope", `endpoints.py` path in the tree).
- `logs/` contains only `proxy.log` after all runs; no `auto_signal.log` was created (tests use tmp paths and delenv `AUTO_SIGNAL_LOG`).
- Not run: any live server (user declined local port binding), `tests/test_main.py`, `uv run`.

## Acceptance criteria
| # | Criterion | Covered by |
|---|---|---|
| 1 | Env-var parity | parity loop printed nothing; set is exactly the five names |
| 2 | Defaults in both files | `.env.example` lines for each var; README "Auto Model" / "Auto Model Signal Log" groups: `claude-proxy-auto`, true (false list `false/0/no/off/blank`, typo stays on), off (`1/true/yes/on`), 5242880 (max 1073741824), 3 (max 20), fail-open vs fail-closed, blank-value warning |
| 3 | Two README sections and greps | both headings present with all listed items; greps for `logs/auto_signal.log`, `analyze_signal_log.py`, `0600`, `95%`, `5%`, `insufficient sample`, `restart`, `ANTHROPIC_CUSTOM_MODEL_OPTION`, `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY` all appear in README.md |
| 4 | Effort docs | README features, env text, table (`xhigh` / `max` row), notes (max accepted at top level, `output_config.effort`, five-step precedence, malformed ignored, `bogus`/`HIGH` 422); QUICKSTART mentions the same levels and carriers and does not contradict; Nemotron `medium_effort` cells say `ultra` only; deepseek-v4.x says `low/high` (medium and max become high) |
| 5 | Docstring-only edit | AST identical, `git diff -U0 -- src/` docstring lines only, diff stat lists the four files; `CLAUDE.md` / `factory/project.md` untouched |
| 6 | Format | black `--check` and isort `--check` pass |
| 7 | Tests | `214 passed`, `239 passed`; no test added/changed; README Testing and QUICKSTART name the five-file command (214), the `--ignore=tests/test_main.py` run (239) and the live-proxy need for `tests/test_main.py` |
| 8 | Context windows | README `### Context windows` after Model Mapping with the values, provenance, and the five caveats (cwd read, startup only, rewrites tracked file, discovery can overwrite curated entries, precedence chain) |
| 9 | No-routing rule | grep reviewed (see above) |
| 10 | Cross-check list | below |
| 11 | "What is NOT verified" | bold paragraph at the end of the README signal-log section with every listed item |

## Criterion 10 cross-check (each verified against merged code)
- [x] False-value list `false|0|no|off|""` after strip+lower; unset/other = true: `src/core/config.py:15-19` (`parse_auto_enabled`), used at `config.py:90`.
- [x] Signal-log truthy list `1|true|yes|on`, else off: `src/core/signal_log.py:33,58-59`.
- [x] Defaults and clamps 5242880 / 1 GiB (1073741824) / 3 / 20; invalid, empty, <=0 -> default; above -> clamped: `signal_log.py:26-31,62-70,371-374`.
- [x] Switch read per request, limits once at handler creation: `signal_log.py:58-59,388` vs `357-377`; `.env` loaded with `load_dotenv(override=True)` at `src/__init__.py:9`.
- [x] File 0600 with `O_NOFOLLOW` where available (+`fchmod`), directory not forced 0700 in a running proxy: `signal_log.py:343-347`; `os.makedirs(..., mode=0o700, exist_ok=True)` at `signal_log.py:367`, but `src/core/logging.py:34` creates `logs/` first at import with default modes.
- [x] Alias before pass-through: `src/core/model_manager.py:22-23` before `:26`.
- [x] Disabled-alias nuance: `model_manager.py:8-13` (`is_auto_alias` false when disabled) then pass-through `:26-36`, haiku/sonnet/opus `:39-44`, default BIG `:45-47`.
- [x] Display name and position: `src/api/endpoints.py:365-371`, appended after the three tier entries; `id` = `config.auto_model_alias` (original casing, `config.py:87-89`).
- [x] Precedence and case rules: `src/conversion/request_converter.py:126-128` (`resolve_client_effort(reasoning_effort, output_config)` then `config.get_effort_default(tier)`), `effort_mapper.py:70-90,110`, `config.py:142-155` (per-tier then `REASONING_EFFORT`); top-level Literal `src/models/claude.py:95` (exact, case-sensitive -> 422), `output_config: Optional[Any]` at `:99` (never rejected).
- [x] No header values; exact hash inputs: `signal_log.py:307-316` (`beta` presence, `sid` + `sid_hash` of `x-claude-code-session-id` via `_hash("sid:", ...)`, `agent`/`parent_agent` presence, `req_class` enum), `:195-226` (`fm_hash` from first user message, `<system-reminder>` blocks removed, whitespace normalised, first 512 chars, `fm_stripped`), `:42-43,91-95` (non-identifier names -> `other`), `_HASH_HEX_CHARS = 8` and unsalted (prefix only).
- [x] Analyzer thresholds 95% / 5% / 10 / 10: `scripts/analyze_signal_log.py:29-31,242`; verdict wording at `:258-267`; exit 2 only with no file `:277`.
- [x] `reason=auto-placeholder|tier-map` on the request log line: `endpoints.py:110-118`.
- [x] 401/422 never logged: auth is a `Depends(validate_api_key)` and body validation precede the handler (`endpoints.py:99-101`); `_emit_signal_safe` is called inside the handler at `:122`, once, above the stream split; it swallows exceptions (`:54-65`).
- [x] HOST/no-key warning: `config.py:38` (`HOST` default `0.0.0.0`), `config.py:28-34` and `endpoints.py:87-88` (validation skipped when `ANTHROPIC_API_KEY` unset).
- [x] Test counts 214 / 239 / 111: measured in this worktree (see commands).

## Carry-forward claims that were wrong or imprecise, and what I wrote
- "Switch and limits read at first use": the switch is read on every request, only the two limits once (when the first record is written). Written that way, plus restart needed because `.env` loads at import and overrides a shell export.
- "`logs/` created 0700 by the module": `src/core/logging.py:34` normally creates it first with default modes. Documented only the 0600 file; "do not assume the directory is 0700".
- "Disabled alias = BIG, `reason=tier-map`": true only for the default `claude-proxy-auto`; custom aliases like `gpt-auto` hit the pass-through, and haiku/sonnet/opus-containing ones map to that tier. Written that way.
- The T1 note's "`gpt-auto` takes the auto branch" is true only while enabled; documented as such implicitly (alias checked first when enabled).
- Spec items (a)/(b): README said deepseek-v4.x gets `low/medium/high`; code (`effort_mapper.py:159-162`) gives `low`/`high` only (medium and max become high). Fixed. README Nemotron table said `medium_effort` for all Nemotron; code (`:151`) sets it only for `ultra` and only at medium/high. Fixed. For `xhigh`/`max` the row now says "thinking on (no `medium_effort`)" (code: canonical `max` -> `enable_thinking` true, no `medium_effort`), whereas the old cell said "full".
- T5 note "switch and limits read when the log is first used": same correction as the first bullet.

## Deviations
- None from the spec. Placed the "What is NOT verified" note and the `ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES` caveat as specified. In the README Testing section I added the sentence that the offline tests assume no `AUTO_*` keys in the environment (from the T1 carry-forward) and that the counts were measured in-process.
- The Claude Code env variable names (`ANTHROPIC_CUSTOM_MODEL_OPTION*`, `CLAUDE_CODE_*`) are from Claude Code docs per the spec; I could not check them against code in this repo and the README says so.
- Existing wording "The proxy routes each level..." in the effort section and `.env.example` "route to each model's native envelope" were left as-is: they refer to effort translation, not the auto model.

## Follow-ups outside this job
- `CLAUDE.md` and `factory/project.md` still carry the stale three-file offline command (111 tests, omits `test_model_manager.py` and `test_signal_log.py`); update to the five-file command (214).
- Job 004 items from the T-decisions stand (8-hex hashes must not be the routing key, `_is_hash` round-trip test, sanitising the model name in the `reason=` log line).
- Live verification of T1-T5 once local port binding is allowed.
