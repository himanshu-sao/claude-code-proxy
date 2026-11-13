APPROVE

Sub-job 003-auto-model-groundwork-t4, build commit 5bfe22e on base 1d5a0e4. The change is data plus tests only: two cache entries and one test class. Nothing under `src/` changed.

## Rationale

- All five acceptance criteria hold. I checked them myself rather than relying on the reviews.
  - `git diff 1d5a0e4 HEAD` touches exactly three files: `model_contexts_cache.json`, `tests/test_context_manager.py` and `build.md`.
  - The cache diff is additions only. It adds the comma after the last old entry plus the two new keys, each `[262144, 32768]`. The 12 existing entries are untouched, there are no duplicate keys, and the file still has no trailing newline.
  - I ran the offline suite from the worktree with the shared venv. `src.__file__` resolved inside the worktree. The result was 42 passed.
  - black and isort `--check` at line length 100 are clean for `src/` and the touched test file.
- The security review (PASS) and code review (PASS) are deserved.
  - The tests only open the cache read-only, never call `run_discovery_and_patch`, and patch `_DISCOVERED_LIMITS` and `_ENV_OVERRIDES` through `monkeypatch`. A developer's `.env` therefore cannot leak in.
  - The shadowing test does exercise the substring loop. It moves the targets last and queries upper-cased ids. It also guards `mistralai/mistral-nemotron` at `(128_000, 16_384)`.
  - The code reviewer showed the tests fail against the pre-change cache.
  - There are no new env vars and no secrets, so `.env.example` and README need nothing for this change.
- Provenance is stated honestly.
  - The commit body says 262,144 is NVIDIA's published hosted spec and was NOT verified live, and that the vendors claim about 1M.
  - It says 32,768 is the repo's own default output cap with no source, and cites precedent c5a0b70.
  - `spec.md`, `build.md` and the parent `answers.md` say the same. Neither file presents the numbers as sourced facts. JSON has no comments, so the commit message is where this caveat lives. It is not in the cache file itself.
  - Both values are the user's recorded decision.
- What the live review would have covered, and what the in-process checks cover.
  - The reviewer's real startup log showed 14 limits loaded from cache. The mistral id was not in the "missing" list, so no upstream lookup was made for it.
  - I ran the actual `run_discovery_and_patch` startup path in-process. The cache was a scratch copy in `$TMPDIR` and the upstream was `http://127.0.0.1:9`. Both ids were configured as models. I did not use a server or bind a port.
  - It loaded the cache, found no missing models, skipped upstream discovery, and did not rewrite the file (sha1 identical before and after). It then returned `(262144, 32768)` from `get_model_limits` for both ids. This closes the reviewer's minimax-on-the-startup-path gap at the function level.
  - The real repo cache file was never written. Its sha1 is still 54271441ec43016e1a484114c0de8f853ffa59cd.
- Operational check, covering the cache-rewrite concern.
  - With both entries present, startup does not touch the file. The two ids count as "known", so the fallback injection (`provider_discovery.py` around 224-235) never runs for them and the `(32000, 4096)` placeholders cannot come back.
  - The earlier placeholder write happened only because the entries were absent. It is a one-time effect, and the entries now close it.

## Unverified

- No live HTTP check ran. The api review is BLOCKED because the sandbox refused to bind a local port. The user declined a rerun with `allowLocalBinding` and chose to proceed. The board keeps `api=BLOCKED`, and I agree it should not be flipped to PASS.
- `get_model_limits` was not observed from a running, bound server. The in-process startup path and the unit tests cover the function and the startup logic. They do not cover the HTTP request path. That path uses the same function, and this job changes no request-path code.
- 262,144 is not verified against the live NVIDIA endpoint, and the vendors claim about 1M. If the real hosted window is smaller, the proxy trims less than it should. The upstream would then answer with a 400, which fails visibly and safely, and the `MODEL_CONTEXT_LIMITS` env override still wins. If the real window is larger, the proxy trims earlier than needed. That is safe but wasteful.
- 32,768 is the repo default output cap. No source gives a real max output for either model.

## Risks and follow-ups (not blockers)

- Other code paths can still change these entries, but only when some other configured model is missing from the cache.
  - In that case `run_discovery_and_patch` calls upstream `/models`. It does `cached_limits.update(new_limits)`, so any metadata the provider returns for these two ids would overwrite `[262144, 32768]`. The new values are then saved back to the tracked file.
  - NIM `/v1/models` normally returns no context metadata, so this is unlikely today. It is still a downgrade path to know about.
  - The same rewrite can also dirty the tracked file for any unrelated model that is missing. This is how the earlier placeholders appeared.
- The cache is read from the CWD (`provider_discovery.py:144`). A proxy started from another directory will not see these entries. It will create a new cache file there.
- Before and after merge, the main checkout's `model_contexts_cache.json` must be clean. If the user's running proxy rewrites it again before the merge, the merge will conflict or be blocked. The proxy must also be restarted after the merge, because the cache loads only at startup.

## Carry forward

- T6 (docs) is not done here, by design. The deferral is recorded in the parent `factory/jobs/003-auto-model-groundwork/refined-prompt.md` on the T6 line. That line says the README must state that the two new context windows are the NVIDIA hosted spec with a repo-default 32,768 output cap. The T4 spec also assigns this wording to the docs task. T6 must carry it, and must not call 262,144 verified or 32,768 sourced.
- Keep `reviews.api = BLOCKED` on the board for T4. The user's waiver is recorded in `answers.md` for this job.
- Optional later cleanup, not needed now. Consider guarding the discovery `update()` so it does not overwrite curated cache entries. A cache-level provenance note would also help, since JSON has no comments.
- The commit trailer says `Claude Sonnet 5.5`, while the profile says `Claude Opus 5.5`. The session attribution instruction takes precedence, so I am not flagging it as a defect.
