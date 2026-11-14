VERDICT: CHANGES

Every round-1 item from my review is fixed in the docs, and the new rework text matches the code except for three small slips (two factual, one typo). Run in the worktree: `src.__file__` resolves inside it, the five-file suite prints `214 passed`, `black --check -l 100 src/` is clean (17 files unchanged), and `isort --check src/` is clean. `git diff -U0 11b8f2a HEAD -- src/` shows only docstring lines in `src/conversion/effort_mapper.py`, and the AST comparison with docstrings stripped is identical (True). The `AUTO_*` set in `src/` is exactly the five names, and all five appear in README, QUICKSTART and `.env.example`.

Findings (fix all three; each is a one-line edit):

1. README.md, "Signal log (Phase 0 capture)" open-proxy warning (the first paragraph, about line 338), last sentence: "A key only protects `POST /v1/messages` and `POST /v1/messages/count_tokens`".
   - The word "only" is wrong. `src/api/compat.py:95-106` defines `_compat_auth`, which calls `endpoints.validate_api_key`. It guards `/api/organizations`, `/v1/organizations`, `/v1/me`, `/v1/oauth/token`, `/v1/mcp_servers`, `/api/connectors` and `/api/plugins`.
   - `/health`, `/test-connection`, `/v1/models`, `/` and the `/api/hello` and `/hello` probes do not check the key.
   - The same "only" appears in `.env.example` (about line 62: "A key only protects /v1/messages and /v1/messages/count_tokens, not /health, /test-connection, /v1/models or /.").
   - Fix, in both files: say "Of the main routes, a key protects `POST /v1/messages` and `POST /v1/messages/count_tokens` (plus the desktop-compat routes such as `/v1/me`); `/health`, `/test-connection`, `/v1/models` and `/` never check it." Drop "only". The practical advice (a key does not protect the health, models or root routes) stays correct.

2. README.md:310 has a stray space before the full stop: "A top-level `reasoning_effort: "max"` is accepted ." Fix: remove the space.

3. README.md "Context windows" (line 220): "If none exists there, the proxy creates one in that directory at startup."
   - In `src/core/provider_discovery.py:135-237`, the file is written only by the background discovery task (`src/main.py:26-40`), and only when `added_to_cache` is true. It is not written when `MODEL_CONTEXT_LIMITS` already covers every configured model (the function returns at line 188-190). With no cache present, any configured model that lacks an env override counts as missing, so the file is normally created.
   - The write also happens after the upstream `/models` call returns or times out (10 s), not synchronously at startup.
   - Fix: "If none exists there, the proxy creates one in that directory shortly after startup, once the background discovery task has run (unless `MODEL_CONTEXT_LIMITS` already covers every configured model)."

Verified fixed (round-1 items), checked in the docs and not only in build.md:
- File mode bullet (README:347): reads "Where `fchmod` exists the file mode is forced to exactly `0600` regardless of umask; without it the umask can only make it stricter". That matches `signal_log.py:343-347`.
- The strict-umask sentence is correct. A directory created by `os.makedirs(mode=0o700)` under umask 0277 comes out `0o500` (I measured this). The later `os.open` then fails and the write is swallowed, visible only at DEBUG.
- Model Mapping alias row (README:207): "checked first, before every other row (including the haiku/sonnet/opus substring rules)" matches `model_manager.py:22-23` coming before `:26` and `:38-44`.
- Disabled-alias paragraph (README:212): I ran the real `ModelManager` with the alias disabled for all ten names. Each result matches the README rule.

  | Alias | Result |
  |---|---|
  | `claude-proxy-auto`, `my-auto`, `fast-auto`, `GPT-auto`, `my-opus-auto` | BIG tier |
  | `gpt-auto`, `o1-auto`, `ep-auto`, `doubao-auto`, `deepseek-auto` | passed through unchanged, tier `unknown` |

  The prefix list and its case-sensitivity are correct, and `doubao-` is at `model_manager.py:32`.
- A grep of the three files finds no "job 004" and no "later job". Both the README and QUICKSTART now say "no routing yet (a planned follow-up)". `.env.example:45-46` uses "groundwork; NO routing yet" and "routing is not implemented yet". The only remaining "Phase 0" is the heading and its cross-references, which are kept deliberately.
- The grep also finds no "content-free", "used to return" or "live suite was not run".
- The counts 214 and 239 appear only in the Testing commands, with one "current numbers, will change" note. QUICKSTART says the 4th `/v1/models` entry is "present only when `AUTO_MODEL_ENABLED` is on". The `fm_hash` order (README:345: reminders removed, then whitespace normalised, then cut to 512 characters) matches `_first_message_hash` at `signal_log.py:195-226`.

New rework text checked against the code, with no other discrepancy:
- HOST and `.env`: `config.py:38` defaults `HOST` to `0.0.0.0`, and `src/__init__.py:9` calls `load_dotenv(override=True)`, which overrides a shell `HOST`. `.env.example:73` ships `HOST="0.0.0.0"` uncommented, and `main.py:103-106` passes `config.host` to uvicorn.
- Placeholder key: `.env.example:6` ships an uncommented placeholder `ANTHROPIC_API_KEY`. Copied verbatim it turns validation on with a public value, as the docs say.
- Retention bullet: the arithmetic holds. 1 active file plus 20 backups is 21 files, and 21 x 1 GiB is about 21 GiB. The defaults give 4 x 5 MiB, about 20 MB. The handler is created with `delay=True` and stays open after the first write, so deleting the file while the proxy runs leaves it writing to an unlinked file.
- Glob sentence, run in scratch directories under the temp dir:
  - zsh with no log: "no matches found", exit 1.
  - bash with no log: the script warns "cannot read logs/auto_signal.log*" and exits 0.
  - With `auto_signal.log` and `.1` present, the unquoted glob in zsh gives "files: 2".
  - A quoted glob matches nothing, so the docs rightly do not advise quoting.
  - No file argument gives usage and exit 2.
- `GET /v1/models` is the 4th entry, appended after the three tier entries only when `auto_model_enabled`. The request log line carries `reason=auto-placeholder|tier-map`.
- The `claude-proxy-auto` text never claims routing. The remaining "route" hits are the quoted display name "Auto (routes to big tier)", which is explained as literal text, the older effort wording, and the `endpoints.py` tree comment.
- Nothing is called verified that was not. The "What is NOT verified" note and the "not checked against a real Claude Code run" sentence remain.
- Markdown: README has 32 code-fence markers and QUICKSTART has 8, both even. The effort table rows keep six columns. The headings are intact: `### Context windows`, `### Selecting the auto model in Claude Code`, `### Signal log (Phase 0 capture)`.
- `model_contexts_cache.json` holds `[262144, 32768]` for both NVIDIA models.

Housekeeping: one of my scratch-directory commands failed on a `mktemp` error and briefly created an empty `logs/auto_signal.log` in the worktree. I deleted it immediately; `logs/` again holds only the gitignored `proxy.log` and `.last_model`. The tracked tree is unchanged apart from this review file and the untracked round-1 security review.
