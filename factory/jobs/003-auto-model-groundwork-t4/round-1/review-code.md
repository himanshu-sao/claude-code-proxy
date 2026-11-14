VERDICT: PASS

- Acceptance criteria 1-5 all hold. I ran them myself in the worktree; `src.__file__` resolved inside the worktree.
  - The AC1 one-liner printed ok: 14 unique keys, and both new ids are `[262144, 32768]`.
  - `git diff 1d5a0e4 HEAD -- model_contexts_cache.json` shows only additions (0 removed lines). Those are the comma after the last old entry plus the two new keys, appended at the end (model_contexts_cache.json:49-57). The "no trailing newline" state is unchanged.
  - The offline suite gave `42 passed`. `black --check -l 100` on `tests/` and `src/` is clean, and `isort --check` is clean.
  - Neither new id overlaps any existing key as a substring, so there is no neighbour shadowing today.
- The tests fail without the cache change, so they are real. I loaded the pre-change cache (`git show 1d5a0e4:model_contexts_cache.json`) into the same fixture state. `get_model_limits` returned `(32000, 4096)` for both ids. That fails `test_exact_lookup` (tests/test_context_manager.py:85-88), `test_cache_file_has_both_ids` (:79-82) and `test_no_neighbour_shadowing` (:91-101).
- The shadowing test is real (tests/test_context_manager.py:91-101).
  - It rebuilds the dict with both targets moved last and queries upper-cased ids. That skips the case-sensitive exact-key check at src/core/context_manager.py:103 and forces the substring loop at :105-107 through every neighbour first.
  - The `mistralai/mistral-nemotron` guard to `(128_000, 16_384)` is present.
  - The build's sensitivity check, which injected a shadowing neighbour, is plausible given how the loop works.
- Isolation is good. The tests never call `run_discovery_and_patch` and never open the cache for writing; the file is only opened with mode "r" (:62). The fixture patches `_DISCOVERED_LIMITS` and `_ENV_OVERRIDES` with `monkeypatch`, so the state is restored and a developer's `.env` `MODEL_CONTEXT_LIMITS` cannot leak in. The `_load_repo_cache` filter matches `provider_discovery.py:152-154`. The code is Python 3.9-safe: `-> dict`, no `match`, and no `X | Y` unions. `git status` shows only the untracked round-1 folder, so no stray cache writes. No `src/` changes and no new env vars, so `.env.example` and README need nothing here. The spec assigns README and QUICKSTART wording to the docs task.
- Commit 5bfe22e states both provenance facts. 262,144 is NVIDIA's published hosted spec and was NOT verified live. 32,768 is the repo's default output cap with no source (precedent c5a0b70). Nits only, neither blocking:
  - `test_cache_file_has_both_ids` (:79-82) partly duplicates `test_exact_lookup`. It is harmless, and it tests the file rather than the lookup.
  - The commit trailer is `Co-Authored-By: Claude Sonnet 5.5`, while `factory/project.md` names `Claude Opus 5.5`. The trailer follows this session's attribution instruction, which takes precedence over the profile, so I am not flagging it as a defect.
