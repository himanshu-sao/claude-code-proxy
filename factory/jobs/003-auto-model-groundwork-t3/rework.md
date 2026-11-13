# Rework note — sub-job 003-auto-model-groundwork-t3 (written by the orchestrator, authorised by the user)

Round 2 came back PASS (security), PASS (code), CHANGES (api, one low-severity finding). The user
approved one extra rework round beyond the usual cap of 2. Scope is exactly the items below; do not touch
anything else. Round-2 files: `round-2/review-api.md`, `round-2/review-code.md`, `round-2/review-security.md`.

## Required fix

1. **Log directory mode** (`src/core/signal_log.py`, the `os.makedirs(os.path.dirname(path), exist_ok=True)` call,
   currently around line 361, in `_ensure_handler`). With umask 022 the directory the module creates comes out 0755, so
   other local users can list it and see the log's name, size and mtime. Create it with `mode=0o700`:
   `os.makedirs(dirname, mode=0o700, exist_ok=True)`.
   - Only a directory the module itself creates is affected. Never chmod or tighten a directory that already exists:
     the project's own `logs/` is created by `src/core/logging.py` at 0755 and must be left alone.
   - Note that `makedirs(mode=...)` is still filtered by the umask and applies only to the leaf in Python 3.7+. If
     parent directories are missing they are created with default modes; that is acceptable, say so in build.md.
   - Add a test with `tmp_path`, an explicit `os.umask(0o022)` (restore it in a finally/fixture), and a log path under a
     directory that does not exist yet: assert the created directory has mode bits `0o700` and the file `0o600`. Add a second
     test that a pre-existing directory with mode 0o755 is left at 0o755 after `emit_signal`.

## Required small fix (raised by the round-2 code and security reviewers)

2. **Analyzer prints `fm_hash` raw** (`scripts/analyze_signal_log.py`, the "top group fm_hash=%s" print near line 210, and any
   other place a hash value is printed with `%s`). A hand-crafted log line can put an ESC byte on the terminal. Print hash values
   through `ascii()` (names and enum values already do), or tighten `_is_hash` to `re.fullmatch(r"[0-9a-f]{1,64}", v)`, or both.
   Add a test: a record whose `fm_hash` contains `\x1b[31m` must not produce a raw ESC byte on stdout, and the analyzer must
   still exit 0.

## Do NOT change

- Hash length (8 hex), salting, the name filter, env clamps, file mode logic, the analyzer's verdict rule and thresholds.
- `src/api/endpoints.py`, `src/core/config.py`, `factory/board.json`, any other sub-job's files.
- The minor non-blocking nits (race test, `sys_str` sentinel, `nonlocal` closures, the not-usable verdict test's exit code)
  unless a fix above touches the same lines.

## Done means

Same rules as before: worktree only, shared venv python with `python -m pytest`, confirm `import src` resolves in the worktree,
offline subset plus `tests/test_signal_log.py` green, black and isort clean at line length 100, Python 3.9-safe, no git stash.
Commit on your branch (conventional message, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`). Update
`build.md`: first line `STATUS: GREEN`, `STATUS: RED` or `STATUS: BLOCKED`, then add a "Rework round 2" section mapping the 2 items to
the code change and the test that covers each. Report the commit SHA and status.

---

# Rework round 3 — integration fix (written by the orchestrator, authorised by the user: "Fix in T3")

All three round-3 reviews passed, but merging T1-T4 in a scratch tree showed a runtime interaction with sub-job T2
that no single-branch review could see. The merge itself is conflict-free; 3 of 178 tests fail on the combined tree:

- `tests/test_signal_log.py::test_sentinels_never_appear_and_fields_are_correct` (`assert rec["oc_effort"] == "other"` got `None`)
- `tests/test_signal_log.py::test_enum_values_are_logged_when_known` (`assert rec["oc_effort"] == "max"` got `None`)
- `tests/test_signal_log.py::test_hostile_names_are_logged_as_other` (hostile `oc_keys` name assertion)

## Cause

Sub-job T2 (branch `factory/003-auto-model-groundwork-t2`, not in your worktree) adds `output_config: Optional[Any] = None` as a
DECLARED field on `ClaudeMessagesRequest` in `src/models/claude.py`. Pydantic stores declared fields as attributes, not in
`model_extra`. Your `build_signal_record` reads `output_config` only from `model_extra` (`src/core/signal_log.py` around line 288:
`output_config = extra.get("output_config") if isinstance(extra, dict) else None`). On the combined tree that is always `None`, so
`oc_keys` and `oc_effort` would be empty even when Claude Code sends effort, which defeats the purpose of Phase 0 (finding which
field carries `/effort`).

## Required fix (the only change in this round)

1. Read `output_config` robustly so it works whether or not T2 is merged: first from the request object's own attribute
   (`getattr`/your existing `_get` helper, which sees a declared field), and if that is `None` fall back to `model_extra["output_config"]`.
   Keep every existing guard (dict check, name filter, enum filter, `_names` cap). A declared-but-None field must not hide an extra value,
   and an extra must not hide a declared value; the declared field wins if both exist.
2. Check the other reads in `build_signal_record` for the same trap: anything that is looked up in `model_extra` but could also
   become a declared field in the future, or is declared in T2's version of the model (T2 changes only `reasoning_effort`'s Literal
   and adds `output_config`). `reasoning_effort` is already a declared field on the base model, so confirm it is read from the
   attribute and say so in build.md. Do NOT change anything else.
3. Tests (your worktree has the BASE model, without T2, so simulate T2): add a test helper that builds a request class equal to
   `ClaudeMessagesRequest` plus `output_config: Optional[Any] = None` (a small subclass in the test file) and run the existing
   output_config assertions against BOTH forms: base model (field lands in `model_extra`) and the subclass (declared field). At
   minimum cover: effort enum value kept (`max`), unknown effort value becomes `other`, hostile `output_config` key names become
   `other`, `output_config` absent, `output_config` of a non-dict type, and a request that has the key both declared and in extras.
   Parametrize the three failing tests above over both request classes rather than copying them.
4. Do NOT edit `src/models/claude.py` (T2 owns it) or `endpoints.py` / `config.py` / `factory/board.json`.

## Done means

Same rules as before: worktree only, shared venv python with `python -m pytest`, confirm `import src` resolves in the worktree, offline
subset plus `tests/test_signal_log.py` green, black and isort clean at line length 100, Python 3.9-safe, no git stash. Commit on your
branch (conventional message, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`). Update `build.md`: first line
`STATUS: GREEN`, `STATUS: RED` or `STATUS: BLOCKED`, then a "Rework round 3" section stating what you changed and which tests cover it.
The orchestrator will re-run the combined T1-T4 merge itself afterwards; you cannot, because T2 is not in your worktree. Report the
commit SHA and status.
