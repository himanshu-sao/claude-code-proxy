VERDICT: CHANGES

Docs-accuracy review of `git diff 11b8f2a HEAD`, each claim checked against merged code. Two factual errors, one misleading table cell, one overbroad sentence, one reader-facing internal reference (job 004), plus nits.

Verified OK (no action):
- `python -c "import src; print(src.__file__)"` resolves inside the worktree.
- The five-file command gives 214 passed. `tests/ --ignore=tests/test_main.py` gives 239. The old three-file command gives 111.
- `black --check -l 100 src/` and `isort --check src/` are clean.
- `git diff -U0 -- src/` shows only docstring lines. An AST comparison with docstrings stripped is identical (True). Both docstrings match `resolve_client_effort`, `normalize_effort` and `get_effort_default`.
- The effort table matches `resolve_effort` cell by cell:
  - GLM-5.x gives low, high, high, max.
  - gpt-oss gives low, medium, high, high.
  - deepseek-v4.1-flash gives low, high, high, high.
  - Nemotron ultra gets `medium_effort` at medium and high only. Non-ultra Nemotron never does. At max, `enable_thinking` is true with no `medium_effort`.
  - Thinking-only models get nothing.
- Pydantic check: top-level `reasoning_effort` `HIGH` and `bogus` fail validation (422), while `max` and `xhigh` are accepted. `resolve_client_effort` strips and lower-cases `output_config.effort` and ignores unknown, non-string or non-dict values.
- `AUTO_MODEL_ENABLED` (fails open) and `AUTO_SIGNAL_LOG` (fails closed) match `config.py:15-19` and `signal_log.py:33,58-59`. The defaults, the clamps and the "invalid, empty or <=0 means default" rule match `_int_env`.
- Switch per request versus limits once at handler creation matches `_ensure_handler`. `.env` overrides a shell export (`src/__init__.py:9`).
- `/v1/models`:
  - The entry is 4th and appended last.
  - The display name is exactly `Auto (routes to big tier)`.
  - The id keeps its original casing.
  - It is absent when the alias is disabled.
- The context-window precedence matches `get_model_limits`, and the cache is read from the CWD at startup only. The tracked file is rewritten when a configured model is missing, and `cached_limits.update(new_limits)` can overwrite curated entries. The provenance wording matches commit 5bfe22e.
- The analyzer thresholds (95%, 5%, 10 sessions, 10 sessions with 2+ turns), the verdict strings, exit 2 only with no file, and the glob `logs/auto_signal.log*` all match `scripts/analyze_signal_log.py`.
- Signal log emission:
  - `_emit_signal_safe` is called once, inside the handler, after auth and body validation, so 401 and 422 are never logged.
  - It runs before the disconnect check, so the "logged once even if the client disconnects" claim holds.
  - `logs/` is created by `src/core/logging.py:34` before the signal log runs, so the "do not assume 0700" wording is right.
  - `logs/` is gitignored, and `proxy.log` is opened with mode "w".
- The claim "offline tests assume no `AUTO_*` keys" is correct. `AUTO_MODEL_ENABLED=false` gives 11 failures and `AUTO_MODEL_ALIAS=foo` gives 10. `AUTO_SIGNAL_LOG=1` still passes.
- Markdown: both files have an even number of code fences, the tables are well formed, the heading levels match the existing style, and there are no new links or anchors to break.
- `.env.example` values, uncommented with the inline `# ...` comments, parse correctly with python-dotenv.
- `logs/` holds only `proxy.log`, and the worktree status shows only my `round-1/` folder.

Findings:

1. **WRONG: the umask claim (README.md:344).**
   - Current text: "the file is opened with mode `0600` (re-applied with `fchmod` where available) and `O_NOFOLLOW` ... (the umask can only make it stricter)".
   - Code: `signal_log.py:343-347` calls `os.open(..., 0o600)` and then `os.fchmod(fd, 0o600)`. `fchmod` is not filtered by the umask.
   - Check: with `umask 0o377`, `os.open` yields 0400 and `fchmod` then yields 0600. On macOS and Linux the file is therefore always exactly 0600, and the umask can loosen it (a 0377 umask gets raised to 0600) as well as tighten it. The claim is right only on platforms without `fchmod`.
   - Fix: replace the parenthetical with "(where `fchmod` exists, the mode is forced to exactly `0600` regardless of umask; without `fchmod`, the umask can only make it stricter)".

2. **MISLEADING: Model Mapping table row (README.md:207, last cell).**
   - Current text: "checked first, before the rows below".
   - Code: `model_manager.py:22-23` checks the alias before the `gpt-`/`o1-`/`ep-`/`doubao-`/`deepseek-` pass-through and before the haiku, sonnet and opus substring rules. The haiku, sonnet and opus rows sit above the alias row in the table, so "the rows below" implies only the pass-through row is overridden.
   - Check: with the alias enabled, a custom alias such as `haiku-auto` or `sonnet-auto` resolves to BIG, not SMALL or MIDDLE.
   - Fix: "checked first, before every other row (including the haiku/sonnet/opus substring rules)".

3. **OVERBROAD: disabled-alias paragraph (README.md:212).**
   - Current text: "a custom alias is not sent to BIG".
   - Code: with the alias disabled, a custom alias such as `my-auto` or `fast-auto` is not matched by any pass-through or substring rule. `model_manager.py:45-47` sends it to the BIG default, which I confirmed by running it. `GPT-auto` (capital G) also lands on BIG because `startswith("gpt-")` is case-sensitive.
   - Only aliases starting with the pass-through prefixes, or containing haiku, sonnet or opus, go elsewhere.
   - Fix: replace the clause with "but a custom alias does not always land on BIG: if it starts with `gpt-`/`o1-`/`ep-`/`doubao-`/`deepseek-` (case-sensitive) it is passed through as-is (tier `unknown`, e.g. `gpt-auto`); if it contains `haiku`, `sonnet` or `opus` it maps to that tier; any other name (e.g. `my-auto`) falls to the BIG default, like any unknown name".

4. **(a) "job 004" is an internal factory id with no meaning to a reader.**
   - Locations: README.md:212, README.md:319, QUICKSTART.md:48, QUICKSTART.md:54. No job 004 exists in the repo. `.env.example:46-47` already says "until a later job", so the three files are also inconsistent.
   - Fix: reword every instance to "no routing is implemented yet (planned follow-up)":
     - README.md:212: "...it always resolves to the BIG tier; routing is not implemented yet (a planned follow-up)."
     - README.md:319: "...does no routing yet (planned follow-up; see Model Mapping)."
     - QUICKSTART.md:48: "(placeholder: no routing yet)".
     - QUICKSTART.md:54: "it does no routing yet (planned follow-up)".
     - `.env.example:46-47`: "until a later release" or "until routing is implemented", with "Phase 0 groundwork" changed to "groundwork".
   - The README heading "Signal log (Phase 0 capture)" is spec-mandated (criterion 3), so I would keep it. Its first sentence already explains the purpose.

5. **Minor, optional.**
   - **Changelog-style and process wording in the user-facing README.**
     - README.md:310: "(it used to return 422)" reads like a changelog line and will go stale. Suggest "A top-level `reasoning_effort: "max"` is accepted."
     - README.md:386: "These counts were measured in-process; the live suite was not run here." The word "here" refers to the build session and means nothing to a reader. Drop it, since the "What is NOT verified" paragraph already covers the live suite.
     - The hard-coded 214 and 239 will drift as tests are added. Consider "(214 tests at time of writing)", or leave the counts out.
   - **QUICKSTART.md:54.** It says "(4th entry in `/v1/models`)" unconditionally. Add "when enabled", since `AUTO_MODEL_ENABLED=false` removes the entry.
   - **`.env.example` trust warning.** The `.env.example` signal-log block says "keep it local" but omits the HOST=0.0.0.0 plus no-`ANTHROPIC_API_KEY` risk that the README states. One line would match the README.
   - **README privacy bullet (line 343).** It lists the `fm_hash` inputs as "512 characters, whitespace-normalised, reminders removed". The code order is remove reminders, then normalise, then truncate to 512. This is an ordering nit only.

(b) Nothing claims `claude-proxy-auto` does routing. Every hit says "BIG tier" or "no routing". The only use of "routes" is the quoted `/v1/models` display name, which is explained as literal text. Nothing is called verified that was not: the live-run gaps, the Claude Code env-var names, `_SUPPORTED_CAPABILITIES` and the thresholds are all disclaimed in "What is NOT verified" and the "not checked against a real Claude Code run" sentence.

(c) The three descriptions of the same variable agree on defaults, truthy and falsy lists, clamps and the blank-value warning. The only gap is the trust-warning one in finding 5.

Cannot re-verify here, and it is disclaimed in the docs: the Claude Code variable names (`ANTHROPIC_CUSTOM_MODEL_OPTION*`, `CLAUDE_CODE_*`) and the write-latency figures.
