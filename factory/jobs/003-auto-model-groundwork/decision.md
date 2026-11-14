APPROVE

Whole-job approval of 003-auto-model-groundwork (T1 to T6) at tip 342998c of feat/virtual-auto-model. `main` is still 377aaed, so the diff is the full job. The non-factory diff is 17 files, +2658/-27. I read the full src/ diff, the docs diff, `signal_log.py` in full, the six sub-job decisions and `board.json`. I also ran the checks below myself.

I approve the branch for a pull request into main. I do not recommend merging directly. The PR should go through human review with the description given at the end.

## Delivery against the promise

Checked against "Confirmed scope of job 003" in answers.md, in the merged code.

1. **Alias handling: delivered.**
   - `ModelManager.is_auto_alias` plus an early return in `map_claude_model_to_openai`. It is checked before the `gpt-`/`o1-`/`ep-`/`doubao-`/`deepseek-` pass-through and before the haiku/sonnet/opus matching.
   - Matching is exact, case-insensitive and whitespace-stripped. It resolves to `get_active_model("big")` with tier `big`, so it follows a BIG fallback.
   - `reason=auto-placeholder` or `reason=tier-map` is appended once to the existing request log line in `create_message`. It is not logged inside the mapper, so the three duplicate lookups do not log it three times.
   - In a TestClient probe (stubbed upstream, written under $TMPDIR) I sent `Claude-Proxy-Auto`. It returned 200, echoed the model unchanged, and logged `tier=big, reason=auto-placeholder`. `claude-opus-4` logged `reason=tier-map`.
   - The existing aliases are unchanged. The diff to the mapper is one early branch.
2. **`/v1/models` entry: delivered.**
   - The alias is appended last, and only when `config.auto_model_enabled` is true.
   - `AUTO_MODEL_ENABLED` defaults to true. The values false/0/no/off/blank disable it, and a typo fails open. The README and `.env.example` both say so.
   - The probe confirmed the 4th entry has the usual fields and display name "Auto (routes to big tier)". The `>= 3` test still passes.
3. **Effort: delivered, with the user's precedence answer.**
   - `ClaudeMessagesRequest.reasoning_effort` now accepts `max`.
   - `output_config` is a declared `Optional[Any]` field, so a malformed value cannot cause a 422.
   - `resolve_client_effort` implements top-level `reasoning_effort` > `output_config.effort`, then per-tier env > `REASONING_EFFORT` > `high`. The converter calls it. A malformed or unknown `output_config` is treated as absent.
   - Top-level `bogus` still returns 422. My probe saw 422 and no signal line for it.
   - `normalize_effort` is unchanged.
4. **Signal log with the user-chosen separate file: delivered.**
   - `src/core/signal_log.py` writes `logs/auto_signal.log` through its own logger with `propagate=False`. It is never written to `proxy.log`.
   - It is a size-capped rotating handler, append mode, and creates `logs/` if missing. The env limits are clamped (20 backups, 1 GiB).
   - The file is created 0600 with `O_NOFOLLOW`. I observed mode 0600 on the file my probe wrote.
   - A write failure is swallowed. It is off by default, and `logs/` is gitignored (`git check-ignore logs` confirms).
   - `scripts/analyze_signal_log.py` is outside pytest. I ran it on my probe file and it exited 0 with a sane summary. An emitted `sid_hash` and `fm_hash` both pass its `_is_hash`.
   - I checked the privacy claim. The probe's message text, `x-api-key` value, session id value and `metadata.user_id` value appeared in none of the 4 emitted lines.
5. **Context-window data: delivered.**
   - `model_contexts_cache.json` gains exactly `[262144, 32768]` for `mistralai/mistral-large-4-1t-a52b` and `minimaxai/minimax-m3.1-flash`. It is a pure addition, there are no duplicate keys, and the file is still tracked.
   - Provenance is stated honestly in the README: the 262,144 is NVIDIA's published hosted spec and not verified live, and the 32,768 is the repo's own default with no source.
   - The values live in the cache only, not in `MODEL_CONTEXT_LIMITS`, as the refined prompt said.
6. **Docs: delivered.**
   - README features, env-var section, model mapping, effort table, "Context windows", "Selecting the auto model in Claude Code", "Signal log (Phase 0 capture)", and the file tree.
   - QUICKSTART and `.env.example` are updated.
   - All five AUTO_* variables appear in both `.env.example` and the README. T6 checked this and I confirmed it by reading the diffs.
   - The `ANTHROPIC_CUSTOM_MODEL_OPTION*` setup, the gateway-discovery variable, the 200K caveat and the single uvicorn process are covered.
   - `_SUPPORTED_CAPABILITIES` is marked unverified and is not promised to work.
7. **Out of scope was respected.**
   - There is no `pick_tier`, no stickiness map, no context-fit routing, no `/health` counters and no startup warning.
   - The three duplicate tier lookups are still there (`endpoints.py` lines 107 and 132, `request_converter.py` line 26).
   - The only `endpoints.py` changes are the `reason=` log argument, `_emit_signal_safe`, the `list_models` entry and its docstring.

## Integration findings

I looked for cross-sub-job defects on the merged tree and found no new bug. The one already known, T2 declaring `output_config` while T3 read only `model_extra`, is fixed. `signal_log.effort()` reads the declared attribute first, then `model_extra`, and a declared None does not hide an extra. My probe showed `output_config` in `body_fields` and `oc_effort: "max"` for an `output_config`-only request, so the log and the converter agree.

- **`endpoints.py` (T1 + T5).**
  - T5 added exactly one call, after T1's single `reason=` line and before conversion, the disconnect check and the stream split.
  - There is one `reason=` line per request, with the signal log on or off.
  - T5's guard evaluates `http_request.headers` and `is_auto_alias` inside its own try/except.
- **Request model (T2) and signal log (T3).** Consistent, as above.
- **`effort_mapper.py` (T2 code, T6 docstrings).**
  - T6 changed docstrings only. T6's decision records that the AST minus docstrings is identical to the T2 base.
  - The docstrings match the code, including the `CLIENT_EFFORTS` tuple.
- **Docs against code on the final tree.** I cross-read README, QUICKSTART, `.env.example` and the code. All of these agree:
  - the variable names and defaults;
  - the clamps (20 and 1 GiB);
  - the fail-open `AUTO_MODEL_ENABLED` against the fail-closed `AUTO_SIGNAL_LOG`;
  - file mode 0600 and the "existing `logs/` keeps its mode" note;
  - "401 and 422 are not logged";
  - "inline write, read once at first write";
  - the precedence chain, in the same wording in README, QUICKSTART, `.env.example` and both docstrings;
  - the endpoint list;
  - the test counts, 214 and 239.
- **Tests across sub-jobs.**
  - `tests/test_endpoints.py` has a T5 autouse fixture. It patches `_log_path` to `tmp_path`, deletes `AUTO_SIGNAL_LOG`, and nulls `anthropic_api_key`. It protects T1's and T5's tests alike.
  - `tests/test_signal_log.py` also patches `_log_path` to `tmp_path`.
  - `tests/test_context_manager.py` reads the tracked cache read-only and monkeypatches the discovery state.
  - I ran the endpoint tests and the five-file set with `AUTO_SIGNAL_LOG=1` exported. The result was 34 passed and 214 passed, and `logs/` gained no `auto_signal.log`.
  - The cache file sha1 was unchanged (54271441...).
- **Residual overlap, minor.** The code-level `is_auto_alias` is called up to twice per request on the request path (the log line and the signal emit). The mapper calls it three more times through the three duplicate lookups. All are O(1) string compares.

## Whole-change review

- **Correctness.** Nothing wrong found. The alias, effort and signal paths behave as specified in my probes. `build_signal_record` is built from independent try/except sections, so a bad field drops only its own keys. The 8-hex hashes are consistent between emitter and analyzer.
- **Security.**
  - The signal log is opt-in, off by default and fail-closed on its switch.
  - No values, text, tool names or base64 are recorded. Logged names must match `[A-Za-z0-9_.:/-]{1,64}`, otherwise they become `other`.
  - The file is 0600 with `O_NOFOLLOW`. Rotation is bounded by the clamps.
  - Who can trigger it: anyone who can send an authenticated and valid `POST /v1/messages`. With `ANTHROPIC_API_KEY` unset and `HOST` defaulting to 0.0.0.0, that is any network peer. The README and `.env.example` warn about this, and about worst-case disk use.
  - The hashes are 32-bit and unsalted. A short prompt can be dictionary-confirmed by someone who can read the file. This is documented and accepted for a capture, and the file is 0600.
  - Identifier-shaped names are logged verbatim, so a secret-shaped string used as a header or field name would be kept. This is documented.
  - I found no new vulnerability.
  - The pre-existing log-injection surface remains: the request log line writes the raw `request.model` into `proxy.log`. T1 did not widen it. The signal log is not affected.
- **Performance.** When the log is off, the request path gets one environment lookup plus one string compare. When it is on, the write is inline on the event loop. The reviewers measured about 0.1 ms typical, 6 to 10 ms for a 2 MB body, and a few ms at a rollover, all in-process and sequential. This is acceptable for an opt-in diagnostic and the README states the cost.
- **Error handling.**
  - The emit helper and the handler swallow everything and log at DEBUG only.
  - A persistently failing write is invisible at the default INFO level (follow-up).
  - Config parsing never raises at import.
- **Python 3.9.**
  - I parsed all 13 changed or added `.py` files with the system python 3.9.6, using `ast.parse(..., feature_version=(3, 9))`. All passed.
  - A grep of the added lines found no `X | Y` runtime annotations, no `match`, no `zip(strict=)`, no parenthesized `with`, no `removeprefix` and no walrus.
  - The code uses `# type:` comments and `typing` generics. The `tuple[str, str]` return annotation in `model_manager.py` is pre-existing and is valid on 3.9.
  - The tests and the code have never been executed on 3.9. The venv is Python 3.14.0, and the repo's `pyproject.toml` has `requires-python >= 3.9`. A syntax parse is not a runtime check.
- **Test quality and isolation.** Confirmed in the integration section. Everything redirects to `tmp_path`, and the real `logs/` and the tracked cache were not touched by the suites or my probes. The T5 reviewers' mutation checks show the endpoint tests fail when the call is removed or duplicated.
- **Maintainability.**
  - `signal_log.py` is 411 lines. It is well sectioned: configuration helpers, builder, handler, emit. I found it readable and it does not need splitting.
  - `tests/test_signal_log.py` is 964 lines. It is large, but the module is a security-sensitive surface and the tests are organised by behaviour.
  - `scripts/analyze_signal_log.py` is 295 lines, standard library only.
  - Together this is about 1,670 lines to maintain for a temporary Phase 0 capture. The PR author should be ready to remove it if the capture is abandoned.
- **Re-runs by me, from ~/Work/src/extra/himanshu-sao/claude-code-proxy.**
  - `src` resolved to this checkout's `src`.
  - The five-file set gave 214 passed.
  - `tests/ --ignore=tests/test_main.py` gave 239 passed.
  - The old three-file command gave 111 passed.
  - `black --check -l 100` on `src/`, `tests/` and the analyzer reported 25 files unchanged. `isort --check --profile black -l 100` was clean.
  - The working tree is clean.
  - I scanned the non-factory diff for literal token-shaped strings and found none.

## Unverified (complete list)

Nothing was run with a live server or a bound port, anywhere in this job.

1. A real uvicorn process:
   - `POST /v1/messages` and `GET /v1/models` over real HTTP, including `reason=auto-placeholder` in real log output;
   - a restart with `AUTO_MODEL_ENABLED=false` or `AUTO_SIGNAL_LOG` set in the process environment;
   - real h11 or uvicorn header parsing (duplicates, casing, order);
   - real upstream streaming and real upstream 4xx/5xx errors, since only stubs were used.
2. Real Claude Code traffic. Whether Claude Code sends `output_config.effort`, which headers it sends, and what its adaptive thinking looks like is still the research assumption. This is what the signal log exists to find out.
3. `ANTHROPIC_CUSTOM_MODEL_OPTION*` and `CLAUDE_CODE_*` behaviour, including `_SUPPORTED_CAPABILITIES` behind a gateway. These come from documentation reading, not from a run. The README says so.
4. The context figures. 262,144 is NVIDIA's spec and was not checked against the live endpoint. The vendors claim about 1M. 32,768 is the repo's own default with no source.
5. The default `_log_path()` resolving to `<root>/logs/auto_signal.log` inside a running proxy. Every test and probe overrode `_log_path`, so the 0600 and 0700 modes were observed on scratch paths only.
6. Event-loop latency under concurrent load and during a rollover. Behaviour at uvicorn shutdown and on real client disconnects.
7. Python 3.9 at runtime. Only a syntax parse was done. No test ran on 3.9.
8. Platforms without `O_NOFOLLOW` or `fchmod`, and multi-worker uvicorn (rotation is not process-safe).
9. The full `uv run pytest tests/` suite, which needs a live proxy on :8082. `tests/test_main.py` never ran.
10. The analyzer's 95% constancy and 5% shared-session thresholds. The README says these are the author's own choice.
11. Board status. The api review is BLOCKED for T1, T2 and T4 (the user waived the live review). T5's api review is PASS but in-process only. T6's code review is CHANGES with all three nits fixed and re-checked by the T6 approver. T3's api PASS used real emit calls and processes but no HTTP.
12. T1+T2+T3+T4 combined-tree checks. I reran the merged result myself on the final tree (the counts above), but I did not rebuild the orchestrator's earlier scratch merge or re-run the reviewers' fault-injection experiments (umask, concurrent processes, rollover, mutation checks).

Honesty of status: I found no claim of live verification in the added code, docs, comments or commit messages. The README's "What is NOT verified" paragraph is accurate and complete against this list. The commit messages state that the live review was waived. The only "live" wording in the added text is "NOT verified live" for the 262,144 window. The deepseek "live-verified" sentence in the README predates this job.

## Follow-ups (deduplicated, blockers marked)

**Blockers for opening a PR: NONE.** I agree with your expectation. Everything below is later work, and the unverified items are disclosed rather than hidden.

Later, in rough priority:
1. **Live verification** of the whole job once local port binding is allowed. Cover Unverified items 1, 2, 5 and 6, and re-check the effort fields against real Claude Code traffic. This is the natural job-004 prerequisite and a good post-PR task.
2. **Python 3.9 runtime run** of the offline tests (for example `uv run --python 3.9`, or a 3.9 venv).
3. **Stale offline test command** in `CLAUDE.md` line 12 and `factory/project.md` lines 9 to 10 (three files, 111 tests). The docs now give the five-file command (214). `factory/project.md` is gitignored, so only `CLAUDE.md` can be part of a PR. It is cheap to fix in the same PR if you want it consistent, but it is not required.
4. **Log injection:** T1's `reason=` request log line writes the raw `request.model` into `proxy.log` and the console. This was already present before the job. Sanitise it in job 004. The signal log is not affected.
5. **`provider_discovery.update()`** can overwrite curated cache entries, including the two new ones, whenever some other configured model is missing from the cache. The README warns about this. The code fix is a guard.
6. **Job 004 constraints, recorded in answers.md:**
   - the 8-hex `sid_hash` and `fm_hash` must never become the routing or stickiness key. The key needs at least 64 bits and must live in memory only, never in a persistent file;
   - add a test that round-trips a real `emit_signal` hash through the analyzer's `_is_hash`. I checked that it matches today;
   - run a combined-tree merge check before individual reviews close when sub-jobs touch the same request model.
7. **`/api/hello` and `/hello` are unauthenticated.** The README's key-protection sentence does not mention them. They are harmless because they cannot reach the signal log.
8. **An older README example** puts an NVIDIA key on a command line (`NVIDIA_API_KEY=nvapi-... uv run scripts/test_nim_effort.py`). It predates the job and is a placeholder.
9. **"content-free" wording** remains in source docstrings and comments (`signal_log.py` lines 1 and 246, `endpoints.py` lines 55 and 120, the analyzer docstring, the `tests/test_signal_log.py` docstring). The docs have corrected the claim to "no raw message text or header values". Reword the code comments in a later change.
10. **Small T5 items:**
    - the `_emit_signal_safe` docstring says "No-op unless AUTO_SIGNAL_LOG is on", but `is_auto_alias` is still evaluated;
    - the T5 `build.md` says +16 lines, the diff is +19;
    - the 5(c) guard test uses `sys._getframe(1).f_code.co_name`. A sturdier form compares code objects;
    - optionally move the `signal_path` fixture to `tests/conftest.py` if another offline module ever POSTs to `/v1/messages`;
    - optionally log a one-time WARNING on the first emit failure, because at INFO level a persistent write failure is invisible.
11. **Doc and operational notes:**
    - running `tests/test_main.py` against a live proxy that has `AUTO_SIGNAL_LOG` on adds lines to that proxy's real log (documented in the README);
    - a `.env` that omits `AUTO_SIGNAL_LOG` does not override a shell export (documented);
    - the cache file is read from the current directory, so a proxy started elsewhere will not see the new entries (documented);
    - if the user's running proxy rewrites the tracked `model_contexts_cache.json` before merge, that is a conflict risk, and the proxy needs a restart after merge for the cache to load.
12. **Commit trailer.** The sub-job commits end with `Claude Sonnet 5.5`, while `factory/project.md` says `Claude Opus 5.5`. The session attribution instruction takes precedence, so this is not a defect. Do not change it in the PR.

## Readiness and PR description

feat/virtual-auto-model is ready to be offered as a pull request into main.

- The delivery matches the confirmed scope, with no out-of-scope drift.
- I found no cross-sub-job defect on the final tree.
- The 214, 239 and 111 test counts reproduce, format checks are clean, and nothing the tests did touched the real log or the tracked cache.
- All new variables are documented in both places.
- I disagree with nothing in the sub-job approvals.

Repo hygiene for the PR:
- The branch carries 61 tracked `factory/` files (about 3,100 lines of job artifacts, boards and reviews) besides the 17 code and docs files. A reviewer should know that `git diff main...HEAD -- . ':!factory'` is the real change.
- `round-1/review-security.md` in T6 is untracked on purpose, because the repo's secret scanner flags the example strings it quotes. Do not add it.

The PR description should say, in plain words:

1. **What it is.** Groundwork only, with no routing:
   - a `claude-proxy-auto` alias (`AUTO_MODEL_ALIAS`) that always resolves to the active BIG model, with a `reason=` field on the request log line;
   - an optional 4th `/v1/models` entry (`AUTO_MODEL_ENABLED`, default on);
   - `reasoning_effort: "max"` accepted, and `output_config.effort` read, with top-level `reasoning_effort` > `output_config.effort` > per-tier env > `REASONING_EFFORT` > `high`;
   - an opt-in, default-off signal log (`AUTO_SIGNAL_LOG`, `logs/auto_signal.log`, 0600, size-capped rotation) plus `scripts/analyze_signal_log.py`;
   - context windows for two NVIDIA models;
   - docs.
2. **Not verified, in bold.** No live server was ever run, because local port binding was declined for the whole job. Everything was checked in-process with FastAPI TestClient and a stubbed upstream, plus unit tests. Also unverified:
   - what real Claude Code actually sends (`output_config.effort`, the headers, adaptive thinking);
   - `_SUPPORTED_CAPABILITIES` and the other `CLAUDE_CODE_*` settings;
   - latency under load;
   - the default log path in a running proxy;
   - Python 3.9 at runtime. Only a syntax parse was done, and the tests ran on 3.14.
3. **Context figures.** 262,144 for the two models is NVIDIA's published hosted spec, not verified live, and the vendors claim about 1M. 32,768 is the repo's own default output cap, not a sourced figure. `MODEL_CONTEXT_LIMITS` still overrides both.
4. **Security notes for the reviewer.** The signal log:
   - is off by default;
   - records identifier-shaped names, counts and enums, plus two unsalted 8-hex hashes, and no values or text;
   - is open to any peer who can reach the proxy when `ANTHROPIC_API_KEY` is unset and `HOST` is 0.0.0.0;
   - writes inline on the event loop, about 0.1 ms typical (in-process, sequential timings).
5. **Review status.** The api reviews for T1, T2 and T4 were BLOCKED and waived by the user, and T5's was in-process only. Offline test counts are 214 (five-file set) and 239 (`tests/ --ignore=tests/test_main.py`).
6. **Follow-ups.** Link the list above, especially job 004's hash-key constraints and the live verification pass.

## Required before opening a PR

NONE.
