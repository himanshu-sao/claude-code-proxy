VERDICT: PASS

Commit cf57e34 reads `output_config` correctly whether the request model declares the field or not. Both runs gave identical log records and identical analyzer output, and the whole round-3 regression set passed again. T3 is not wired into /v1/messages (that is T5), so there is no HTTP surface. I started no server and ran plain python processes.

Setup
- Worktree `.../.claude/worktrees/003-t3`, HEAD `cf57e34`.
- `export PY=<repo>/.venv/bin/python PYTHONPATH=$PWD OPENAI_API_KEY=test-key AUTO_SIGNAL_LOG=1`.
- `$PY -c "import src; print(src.__file__)"` printed `<worktree>/src/__init__.py`.
- Scratch is `$TMPDIR/t3r4` (/tmp/claude-501/t3r4). The round-3 drivers are reused from `$TMPDIR/t3r3` (`run.py`, `driver.py`, `gen.py`, `synth.py`, `clamp.py`, `hostile.py`, `hostile2.py`). `run.py` monkeypatches `signal_log._log_path` to a scratch dir.
- The real `logs/` held only `proxy.log` before and after, with md5 bf971d15... unchanged.

1. This round's focus: plain vs declared-field request class
- Driver: `$TMPDIR/t3r4/drv4.py <plain|declared> 300`. It builds Claude Code-shaped requests: a 30-tool list, a 40 KB system prompt, 7 messages with thinking, tool_use and tool_result blocks, `thinking {type: adaptive}`, `metadata.user_id`, and `x-api-key` and `User-Agent` headers.
- Every request carries `output_config {"effort": "max"}`. Every third request (i % 3 == 0) also has top-level `reasoning_effort: "high"`. Every tenth is a subagent (`x-claude-code-agent-id`). Auto-alias flag alternates.
- `plain` uses `ClaudeMessagesRequest` unchanged. The driver printed `oc declared: False extra: allow`.
- `declared` uses `class Declared(ClaudeMessagesRequest): output_config: Optional[Any] = None`. The driver printed `oc declared: True extra: allow`.
- Commands: `SCRATCH=$T/plain $PY $T/drv4.py plain 300` and `SCRATCH=$T/declared $PY $T/drv4.py declared 300`, both rc 0.

| Check | plain | declared |
|---|---|---|
| Lines / bytes | 300 / 200,970 | 300 / 200,970 |
| File / dir mode | `-rw-------` / `drwx------` | `-rw-------` / `drwx------` |
| Lines failing `^YYYY-MM-DD HH:MM:SS,mmm \| AUTOSIGNAL \{` | 0 | 0 |
| Records with `oc_keys == ["effort"]` and `oc_effort == "max"` | 300 of 300 | 300 of 300 |
| `reasoning_effort` | "high" in 100, null in 200 | "high" in 100, null in 200 |
| `body_fields` (first record) | `max_tokens, messages, metadata, model, output_config, reasoning_effort, stream, system, thinking, tools` | the same |

- Leak greps in both logs gave 0 for SECRETKEY, user_secret, "You are Claude", CLAUDE.md, claude-cli, tool_1, hmm, line2, system-reminder, "date 2026", S-sess and "hello world".
- Difference between the two logs, using `$T/cmp.py`:
  - Records compared field by field: 300 of 300 are identical. The set of differing keys is empty.
  - Message part after the timestamp, as raw text: 0 lines differ.
  - So the two runs differ only in the timestamps. The `body_fields` shows `output_config` in both, because `model_fields_set` includes it once declared.
- Analyzer on each log: `$PY scripts/analyze_signal_log.py $T/<m>/logs/auto_signal.log`.
  - Both exit 0 with 0 stderr bytes, and `diff an-plain.txt an-declared.txt` reports no differences.
  - "Effort and thinking presence" is the same for both, and for both the auto and non-auto groups:

| Group | reasoning_effort set | output_config.effort set | thinking set | thinking budget set | anthropic-beta | oc_effort values | think_type values |
|---|---|---|---|---|---|---|---|
| auto (150) | 50 (33.3%) | 150 (100.0%) | 150 (100.0%) | 0 (0.0%) | 150 (100.0%) | `'max'`: 150 | `'adaptive'`: 150 |
| non-auto (150) | 50 (33.3%) | 150 (100.0%) | 150 (100.0%) | 0 (0.0%) | 150 (100.0%) | `'max'`: 150 | `'adaptive'`: 150 |

  - `reasoning_effort` values are `'high'`: 50 in each group.
- Edge cases for `output_config`, run against both classes (`$T/oc.py`). The results were identical for the two classes:
  - `{"effort": "max"}` gave `(['effort'], 'max')`, and `"MAX"` gave `(['effort'], 'max')`.
  - `"bogus value"` and `5` gave `(['effort'], 'other')`.
  - Absent, `None`, and a non-dict `"max"` gave `([], None)`.
  - A hostile key set (space, ESC, café, `SECRET TEXT: hunter2`, 65 x's) plus `effort: low` gave `['effort', 'other' x5]` with `oc_effort` `low`.
- Precedence with `model_construct`, so the declared value and an extra differ:
  - Declared None with an extra `{"effort": "high"}` gave `['effort'], 'high'`. The extra is not hidden by a declared None.
  - Declared `max` with an extra `low` gave `['effort'], 'max'`. The declared value wins.

2. Round-3 regression set (all PASS)
- The round-3 drivers ran against cf57e34.
- 300 emits (`loop 300 runA`): 300 lines and 198,450 bytes, the same as rounds 2 and 3. 0 lines failed the format regex. The leak greps gave 0 for the same twelve strings.
- Restart/append: a second process (`loop 100 runB`) took the file to 400 lines.
- Rotation: `AUTO_SIGNAL_LOG_MAX_BYTES=20000 AUTO_SIGNAL_LOG_BACKUP_COUNT=2`, 300 emits. Result: `auto_signal.log`, `.1` and `.2`, each 30 lines and 19,845 bytes, all `-rw-------`, no `.3`.
- Concurrency: 4 background processes with 200 emits each gave 800 lines and 0 unparseable.
- Disabled by default: with `AUTO_SIGNAL_LOG` unset, empty, `0` and `false`, no scratch dir or file was created.
- Unwritable path: a regular file where `logs/` should be gave rc 0 and 0 stderr bytes. A chmod 500 dir gave rc 0 and 0 stderr bytes.
- Symlink at the log path: rc 0, 0 stderr bytes, the victim file still held `ORIG` and the symlink was intact.
- Env clamps:
  - `BACKUP_COUNT=5000000 MAX_BYTES=99999999999999999999` gave `maxBytes 1073741824, backupCount 20`. Three forced rollovers each took 0.000 s.
  - BACKUP_COUNT 20 and 21 both gave 20. MAX_BYTES 1073741824 and 1073741825 both gave 1073741824.
  - Invalid values `abc`, `0`, `-5` and empty gave rc 0 and empty stderr, 4 of 4.
  - My `clamp.py` prints whichever limit was not set as its default, which is why some lines show `5242880` and `3`.
- Huge ints: `max_tokens=10**5000` with `budget_tokens=10**5000` gave 1 line, `max_tokens` None, `think_budget` None and `think_type` "enabled". `True`, `1.5`, `-1`, `2**53` and `"9"` gave None. `2**53-1` was kept.
- Hostile names in model, body fields, headers, `output_config` keys and `metadata` keys:
  - Names with a space, ESC, café, RLO, 65 x's, an empty string, a newline and `SECRET TEXT: hunter2` were all logged as `other`. A 64-character name was kept.
  - The line was pure ASCII and contained none of hunter2, SECRET, ESC, evil, caf, space or break.
  - Legitimate names `anthropic-beta` and `x-custom_hdr.1` passed through.
  - The same held through `model_fields_set` on a real `ClaudeMessagesRequest`.
- Directory modes:

| Case | Directory | File |
|---|---|---|
| umask 022, 077 and 000, fresh tree | `drwx------` | `-rw-------` |
| Existing `logs/` at 0755 | left at `drwxr-xr-x` | `-rw-------` |
| Existing `logs/` at 0750 | left at `drwxr-x---` | not checked |

- `$PY -m pytest tests/test_signal_log.py -q` gave 65 passed.

3. Analyzer (`scripts/analyze_signal_log.py`), logs from the real `emit_signal`
- All runs exited 0 with empty stderr. The figures match round 3.

| Log | Measured | Verdict |
|---|---|---|
| 1 session, 3 turns | constancy 100.0% (1 of 1), shared 0.0% | insufficient sample (1 sessions, 1 with 2+ main-thread turns; need at least 10 of each) |
| 12 clean sessions, unique first messages, 3 turns each | constancy 100.0% (12 of 12 sessions, 36 turns), shared 0.0% (0 of 12) | `fm_hash is usable (thresholds met)` |
| 12 sessions, same first message | constancy 100.0% (12 of 12), shared 100.0% (12 of 12) | `NOT shown to be usable (thresholds not met)` |
| 12 sessions, first message changes per turn | constancy 0.0% (0 of 12), shared 0.0% | NOT shown to be usable |
| 9 clean sessions | constancy 100.0% (9 of 9), shared 0.0% | insufficient sample (9 sessions, 9 with 2+ main-thread turns) |
| 12 sessions, 1 turn each | constancy n/a (0 of 0), shared 0.0% | insufficient sample (12 sessions, 0 with 2+ main-thread turns) |
| 1 session, 4 main-thread turns plus 1 subagent record | constancy 100.0% (1 of 1, 4 main-thread turns); subagent/auxiliary share 1 of 5 (20.0%) | insufficient sample |

- Empty file: rc 0, `records: 0`, verdict "undetermined (no records with both hashes)".
- Garbage file (text, `AUTOSIGNAL not json`, `AUTOSIGNAL [1,2]`, binary bytes): rc 0, 0 tracebacks, `records: 0`, 2 skipped.
- Rotated trio: files 3, records 90, skipped 0, rc 0.
- A missing path plus a valid file: warning on stderr, rc 0. No arguments: rc 2.
- Deep nesting (`'['*300000` and `'{"a":'*100000`): rc 0, 0 tracebacks, verdict "undetermined".
- ESC hash: I took a real 12-session log and edited `fm_hash` to `\x1b[31mRED` on every third record, `sid_hash` to `ab\x1b]0;pwn\x07` on every fifth, plus `DEADBEEF` and a 65-character hash.
  - Result: rc 0, 0 raw ESC bytes on stdout or stderr, 0 BEL bytes, and none of "RED" or "DEADBEEF" in the output.
  - 36 records were parsed and 0 skipped. The verdict was "insufficient sample (11 sessions, 6 with 2+ main-thread turns)".

Cleanliness
- `git status --short` shows only the untracked `factory/jobs/003-auto-model-groundwork-t3/rework.md`, `round-1/` to `round-4/` (this file is in `round-4/`). `git diff` is empty, so no tracked file was modified.
- The real `logs/` still holds only `proxy.log` (md5 unchanged). No server was started or left running, and I created no git worktrees and ran no state-changing git commands. Nothing was blocked by the sandbox.
- I made one mistake while running the regression set. My first analyzer batch used a zsh variable holding a command with a space, so every call failed with "no such file". I reran the batch with a shell function. Only the results of the rerun are reported above.
