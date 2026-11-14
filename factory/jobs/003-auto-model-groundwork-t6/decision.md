APPROVE

Sub-job 003-auto-model-groundwork-t6 (docs), branch factory/003-auto-model-groundwork-t6, head 97ab897 (docs head 6e1f4c7). Judged against spec.md, the refined-prompt addenda, the three rounds of reviews and the code in the worktree.

## Reasoning

- **The 5-line delta (`git diff ae1ae5b 6e1f4c7`) is correct. I re-checked it myself.**
  - Key-protection sentence (README line 338, `.env.example` lines 62-63). Every route it names is behind `_compat_auth` in `src/api/compat.py`: `/v1/me`, `/api/organizations`, `/v1/organizations`, `/v1/oauth/token`, `/v1/mcp_servers`, `/api/connectors` and `/api/plugins`. `_compat_auth` delegates to `validate_api_key`.
  - The catch-all route `/{full_path:path}` has no key dependency. It only returns a 404 error body, so it is not a data route.
  - In `src/api/endpoints.py`, only `POST /v1/messages` and `POST /v1/messages/count_tokens` use `Depends(validate_api_key)`. `/health`, `/test-connection`, `/v1/models` and `/` do not, which is what the docs now say.
  - `/api/hello` and `/hello` also have no key check. The sentence does not claim they do, so it is not false, only not exhaustive.
  - The word "only" is gone. Grep finds no "only protects", no "content-free", no "job 004" and no stray ` .`.
  - Stray space: `is accepted.` is fixed.
  - Cache-file timing (README line 220). The new text says the file is created "shortly after startup, once the background discovery task has run (unless `MODEL_CONTEXT_LIMITS` already covers every configured model)". This matches the code.
    - `src/main.py` starts `run_discovery_and_patch` with `asyncio.create_task` at startup.
    - `provider_discovery.py` returns early when no configured model is missing from the env overrides or the cache. It writes the file only when `added_to_cache` is true.
    - "Read from the current directory at startup only" is also accurate (`cache_file = "model_contexts_cache.json"`, a relative path).
- **Checks I re-ran in the worktree:**
  - `import src` resolves inside the worktree.
  - The five-file suite prints `214 passed`.
  - black `--check -l 100 src/` reports 17 files unchanged, and isort `--check` is clean.
  - The AST of `src/conversion/effort_mapper.py` with docstrings stripped is identical to `11b8f2a`. The src diff is two docstrings only.
  - The AUTO_* parity loop prints no MISSING line. The set is exactly the five names.
  - `git diff --stat 11b8f2a HEAD -- . ':!factory'` lists only README.md, QUICKSTART.md, .env.example and `src/conversion/effort_mapper.py`.
  - CLAUDE.md and `factory/project.md` are untouched.
  - `logs/` holds only `proxy.log`. No `auto_signal.log` was created.
- **Review findings:** round 1 (security CHANGES, code CHANGES, api PASS) was addressed in the round-1 rework. Round 2 came back security PASS, api PASS, code CHANGES with three one-line slips. All three are fixed and verified above. I read `round-1/review-security.md` from disk. Its items (open-proxy warning, privacy over-claim, retention order) are present in the docs, and the round-2 security review confirmed them.
- **No routing claim.** Every grep hit for `rout*` near `claude-proxy-auto` says "BIG tier" and "no routing yet (a planned follow-up)". The only other use is the quoted `/v1/models` display name "Auto (routes to big tier)". The remaining hits are effort-translation wording and a file-tree comment, which have nothing to do with the alias.
- **Provenance is honest.** README line 218 says 262,144 is NVIDIA's published hosted spec, **NOT verified live**, and that vendors claim about 1M. The next line says 32,768 is the repo's own default output cap, with no source. The cache file does hold `[262144, 32768]` for both models, as the round-2 reviewer found.
- **"What is NOT verified" note (README line 358) is honest and complete.** It lists:
  - no live HTTP run (local port binding was declined, in-process checks only);
  - the real Claude Code request shape and `_SUPPORTED_CAPABILITIES`;
  - the 262,144 and 32,768 figures;
  - latency under load, shutdown and real disconnects;
  - default log-path modes in a running proxy;
  - platforms without `O_NOFOLLOW`;
  - multi-worker use;
  - the 95%/5% thresholds;
  - the full live suite.

  The latency figures are labelled "measured in-process only, not under concurrent load". The only "live-verified" wording in the docs is the pre-existing deepseek-v4.1-flash sentence, which this job did not write.
- **Project rules.** All five AUTO_* variables are in both `.env.example` and the README Environment Variables section, with defaults, clamps, the fail-open and fail-closed contrast, and the blank-value warning. README features, the effort table (including the Nemotron `ultra`-only `medium_effort` and the deepseek `low/high` fixes), QUICKSTART and the Testing section are in sync. The three spec-mandated README headings are present.
- **Promises from T1-T5 to the docs:** I found none missing. The T1 alias and display-name facts, T2 precedence and `max`, T3 limits and file mode, T4 windows and cache caveats, and T5 accepted-request, 401/422, open-proxy, restart and write-failure facts are all documented.

## Unverified

- No live server was run, in this job or by me. Nothing was started and no port was bound.
- I did not re-run the umask, glob-expansion, `ModelManager` alias and disabled-alias matrix experiments. I relied on the round-1 and round-2 reviewers' tests and on reading `signal_log.py` and `model_manager.py`. The README text matched what I read.
- I did not re-check the Claude Code environment variable names (`ANTHROPIC_CUSTOM_MODEL_OPTION*`, `CLAUDE_CODE_*`). The docs disclaim them as taken from Claude Code docs and not checked against a real run.
- I did not run the 239-test broader run or `tests/test_main.py`.
- The 5-line delta was not re-reviewed by a fourth reviewer round. I checked it myself against the code, as described above.

## Carry forward

- `CLAUDE.md` and `factory/project.md` still carry the stale three-file offline test command (111 tests). The docs now give the five-file command (214). Update both.
- The words "content-free" remain in source docstrings in `src/core/signal_log.py` (for example `signal_log.py:246`, "Build the content-free record") and `src/api/endpoints.py`, and in `tests/test_signal_log.py`. The docs no longer use them. Reword the code comments in a later code job.
- T1's `reason=` log line writes the raw model name into `proxy.log`, a pre-existing log-injection surface. Sanitise it in the routing job.
- `update()` in `provider_discovery.py` can overwrite curated cache entries. The README already warns about this, so the code fix is a follow-up.
- An older README example puts an NVIDIA key on a command line (`NVIDIA_API_KEY=...`). It predates this job and was non-blocking in both security rounds.
- The key-protection sentence does not mention the unauthenticated `/api/hello` and `/hello` probes. This is harmless, since they cannot reach the signal log.
- A `.env` file that omits `AUTO_SIGNAL_LOG` does not override a shell export of it. The docs say `.env` overrides only the keys it contains, so this is not a doc error.
- Live verification of T1-T5 once local port binding is allowed.
- The final whole-job (003 T1-T6) pass should confirm the README and code still agree after any merge-order changes. The 214 and 239 counts are labelled in the docs as current and expected to drift.

## Required before merge

NONE.

Commit `round-1/review-security.md` only deliberately if at all. It is untracked on purpose because the repo's secret scanner flags the key-like example strings it quotes. It is not needed for the merge.
