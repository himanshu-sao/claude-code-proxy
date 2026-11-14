# Rework note, sub-job 003-auto-model-groundwork-t6 (docs), round 1 (written by the orchestrator)

Round 1 came back: security CHANGES, code (accuracy) CHANGES, api (run the docs) PASS. This is the single consolidated list.
Review files: `round-1/review-security.md`, `round-1/review-code.md`, `round-1/review-api.md`. Read all three first.
Scope is documentation only. Same rules as before: worktree only, shared venv python with `python -m pytest`, no source edits
beyond the two docstrings already changed (and only if a docstring itself is inaccurate), no CLAUDE.md, no factory/project.md, no
board.json. Verify every statement you write against the code; the orchestrator re-checked the facts marked VERIFIED below.

## A. Security review (all documentation)

1. **Open-proxy warning is too hidden and its mitigation is incomplete.** Today it is the 8th bullet of the README signal-log section
   and appears nowhere else. Fix:
   - Put it FIRST in the README "Signal log (Phase 0 capture)" section, and add it to `.env.example` next to `AUTO_SIGNAL_LOG`, to
     the README Features bullet for the signal log, and as one sentence in QUICKSTART where the signal log is mentioned.
   - Say what actually protects an operator. VERIFIED: `.env` is loaded with `load_dotenv(override=True)` and `.env.example` ships
     `HOST="0.0.0.0"` uncommented, so `HOST=127.0.0.1 ./start.sh` on the command line does NOT take effect when `.env` sets HOST: edit
     `.env`. Binding `HOST` to a loopback address is the strongest fix.
   - VERIFIED: `.env.example` ships the public placeholder `ANTHROPIC_API_KEY="your-expected-anthropic-api-key"`, which is a live key if
     copied verbatim: tell the user to replace it with a private random value (or remove it deliberately).
   - VERIFIED in `src/api/endpoints.py`: only `POST /v1/messages` and `POST /v1/messages/count_tokens` use `validate_api_key`. `/health`,
     `/test-connection`, `/v1/models` and `/` do not, so setting a key does not protect them.
2. **Privacy headline over-claims.** "content-free" (README.md Features bullet, README Project Structure comment) and "never message
   text" (`.env.example`) need softening to "no raw message text or header values". Wherever the headline appears, also say, briefly:
   the two 8-hex hashes are UNSALTED and a short or templated prompt can be confirmed by guessing; `fm_hash` is only 32 bits; and any
   identifier-shaped name (body field, header name, `output_config` or `metadata` key, model name, matching `[A-Za-z0-9_.:/-]{1,64}`)
   is logged verbatim, so a key-like string used as a name (for example one starting `sk-` or `ghp_`) would be kept. The detailed README
   privacy bullet is already accurate; make the other places consistent with it.
3. **Retention advice is incomplete.** Replace "delete it after the capture" (README and `.env.example`) with: turn `AUTO_SIGNAL_LOG` off
   and restart FIRST (the handler keeps the file open, so deleting it while the proxy runs leaves the proxy writing to an unlinked
   file), then delete `logs/auto_signal.log*` including the rotated files. State the worst case disk use: up to 21 files x 1 GiB = about
   21 GiB at the maximum clamps, and an unauthenticated peer can drive it when the proxy is open; advise keeping the defaults (about 20 MB).

## B. Code (accuracy) review

4. **README "File mode" bullet (about line 344): the umask clause is wrong.** VERIFIED: where `os.fchmod` exists the file is forced to
   exactly `0600` whatever the umask (tested umask 0022, 0077, 0277, 0377 on an existing writable directory). Reword to: "where `fchmod`
   exists the file mode is forced to exactly `0600` regardless of umask; without it the umask can only make it stricter". Optional one
   line: if the module itself has to create the directory under a very strict umask (for example 0277) the directory can come out
   non-writable and the write is silently skipped (failures are swallowed and only visible at DEBUG).
5. **README Model Mapping alias row (about line 207):** "checked first, before the rows below" is wrong, the alias row sits BELOW the
   haiku, sonnet and opus rows. Say "checked first, before every other row (including the haiku/sonnet/opus substring rules)".
6. **README disabled-alias paragraph (about line 212) is too broad.** VERIFIED with the real `ModelManager`, alias disabled: `claude-proxy-auto`,
   `my-auto`, `fast-auto`, `GPT-auto` and `my-opus-auto` all resolve to `('<BIG model>', 'big')` (the last because `opus` maps to the big
   tier); `gpt-auto`, `o1-auto`, `ep-auto` and `deepseek-auto` pass through unchanged with tier `unknown`. Write exactly that rule: the
   pass-through prefixes `gpt-`, `o1-`, `ep-`, `doubao-`, `deepseek-` are case-sensitive and checked first; otherwise a name containing
   `haiku`, `sonnet` or `opus` (case-insensitive) maps to that tier; everything else, including the default alias, goes to BIG with
   `reason=tier-map`. Re-verify `doubao-` against `src/core/model_manager.py` before you state it.
7. **"job 004" must be reworded** in README.md (about lines 212 and 319), QUICKSTART.md (about lines 48 and 54): it is an internal
   factory id that means nothing to a reader. Use "no routing yet (a planned follow-up)" in all four places. Make `.env.example`
   (about lines 46-47: "until a later job", "Phase 0 groundwork") consistent with that wording. Keep the heading "Signal log (Phase 0 capture)".
8. **Minor, do these too (cheap):**
   - README "(it used to return 422)" changelog wording: remove the parenthetical.
   - README "the live suite was not run here" (about line 386): build-session wording, remove it (the "What is NOT verified" note covers it).
   - Hard-coded test counts will drift: keep them but say "currently 214 / 239" once, in one place.
   - QUICKSTART: say the 4th `/v1/models` entry exists only when `AUTO_MODEL_ENABLED` is on.
   - README privacy bullet: the `fm_hash` input order is: remove `<system-reminder>` blocks, THEN normalise whitespace, THEN truncate to the
     first 512 characters (VERIFIED in `src/core/signal_log.py` `_first_message_hash`). Fix the wording.

## C. Run-the-docs review (PASS, three small nits to fold in)

9. The umask clause (same as item 4).
10. VERIFIED: under zsh, `python3 scripts/analyze_signal_log.py logs/auto_signal.log*` fails with "no matches found" when no log exists
    yet (bash passes the literal pattern, the script then warns and exits 0). VERIFIED: `scripts/analyze_signal_log.py` does NOT expand
    globs itself (it only reads `sys.argv`), so do NOT tell users to quote the glob: a quoted pattern would be taken as one literal file
    name and match nothing. Keep the unquoted form `logs/auto_signal.log*` and add one sentence: the shell expands the glob, so run it
    after the log exists (zsh stops with "no matches found" otherwise; bash passes the pattern through and the script warns about a
    missing file and exits 0).
11. When no `model_contexts_cache.json` exists in the current directory, the proxy creates one there at startup (VERIFIED by the
    run-the-docs reviewer): add one sentence in the README "Context windows" section.

## Do NOT

- Do not claim anything is verified that no live server checked. Keep the "What is NOT verified" note and extend it only if you add
  a new unverified claim.
- Do not describe `claude-proxy-auto` as routing. Do not touch CLAUDE.md or factory/project.md.
- Do not change code. If you find a docstring inaccuracy, fix the docstring only and say so.

## Done means

Re-run: `python -c "import src; print(src.__file__)"` (inside the worktree); the five-file suite must still print `214 passed`; black and
isort at line length 100; the env-var parity loop (every `AUTO_*` in `src/` in both `.env.example` and README); the AST-identical check
of `src/conversion/effort_mapper.py` against `11b8f2a` with docstrings stripped; `git diff --stat 11b8f2a HEAD` touches only README.md,
QUICKSTART.md, .env.example, `src/conversion/effort_mapper.py` (docstrings) and the job folder. Commit on your branch (docs: ... with the
trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`), update `build.md` (first line `STATUS: GREEN`, `RED` or `BLOCKED`, plus
a "Rework round 1" section mapping items 1-11 to what you changed and the file:line, and anything you decided NOT to do and why).
Report the commit SHA and status.

---

# Rework round 2 (written by the orchestrator, authorised by the user: "One more rework round")

Round 2 came back: security PASS, api (run the docs) PASS, code (accuracy) CHANGES with three one-line slips. I checked all three against
the code and they are real. Docs only. Same rules as before: worktree only, shared venv python with `python -m pytest`, no source edits,
no CLAUDE.md, no factory/project.md, no board.json. Read `round-2/review-code.md` first.

1. **The key-protection sentence is false as written.** README.md "Signal log (Phase 0 capture)" open-proxy paragraph (about line 338)
   says "A key only protects `POST /v1/messages` and `POST /v1/messages/count_tokens`; `/health`, `/test-connection`, `/v1/models` and
   `/` never check it", and `.env.example` (about lines 62-63) says the same. VERIFIED in `src/api/compat.py` (line 95 `_compat_auth`
   delegates to `validate_api_key`): the key is ALSO enforced on the desktop-compat routes `GET /api/organizations`, `GET /v1/organizations`,
   `GET /api/organizations/{org_id}` (and `/v1/...`), `GET /api/organizations/{org_id}/{resource_path}`, `GET /v1/me`,
   `POST /v1/oauth/token`, `GET /v1/mcp_servers`, `GET /api/connectors` and `GET /api/plugins`. VERIFIED: the compat catch-all
   (`compat_catch_all`, line 179) has NO key dependency: it only returns a 404 error body for unknown paths and is not a data route.
   Rewrite both places to say: a configured key protects `POST /v1/messages`, `POST /v1/messages/count_tokens` and the desktop-compat
   routes (`/v1/me`, `/api/organizations`, `/v1/organizations`, `/v1/oauth/token`, `/v1/mcp_servers`, `/api/connectors`, `/api/plugins`);
   it does NOT protect `/health`, `/test-connection`, `/v1/models` or `/`. Drop the word "only". Keep it short in `.env.example`
   (name the two POST routes and say "and the desktop-compat routes"). Then grep README.md, QUICKSTART.md and `.env.example` for any
   other sentence that says or implies which routes a key protects, and make every one consistent.
2. **README.md line 310:** a stray space before the full stop (`is accepted .`). Fix it. grep the three files for other ` .` or ` ,`
   typos you may have introduced.
3. **README.md line 220 (Context windows):** "If none exists there, the proxy creates one in that directory at startup." is imprecise.
   VERIFIED in `src/core/provider_discovery.py` (lines 135-237) and `src/main.py` (the discovery runs as a background `asyncio` task): the
   file is written by the background discovery task shortly after startup, only when at least one configured model has no known limit
   (if `MODEL_CONTEXT_LIMITS` or the cache already covers every configured model it is not written), so a missing file is created
   "shortly after startup, once background discovery has run, unless `MODEL_CONTEXT_LIMITS` already covers every configured model".
   Also re-read the same sentence's other claims ("read from the current directory at startup only") and keep them accurate.

## Done means

Re-run and report: `python -c "import src; print(src.__file__)"` (inside the worktree); the five-file suite prints `214 passed`;
black and isort at line length 100; the AUTO_* parity loop; the AST-identical check of `src/conversion/effort_mapper.py` against
`11b8f2a` with docstrings stripped; `git diff --stat 11b8f2a HEAD -- . ':!factory'` touches only README.md, QUICKSTART.md,
.env.example and `src/conversion/effort_mapper.py`; and grep proof that the old "only protects" wording and the stray ` .` are gone.
Commit on your branch (docs: ..., trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`) and add a "Rework round 2"
section to `build.md` (first line stays `STATUS: GREEN`, `RED` or `BLOCKED`) mapping the three items to what you changed and where.
Do NOT commit `round-1/review-security.md` (it quotes key-like example strings that the commit hook flags as a false positive).
Report the commit SHA and status.
