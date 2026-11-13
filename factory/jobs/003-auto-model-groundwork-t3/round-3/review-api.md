VERDICT: PASS

The round-2 finding is fixed: the directory `emit_signal` creates is now 0700 and the file 0600. All round-2 regression scenarios pass on commit 1a8143b. T3 is not wired into /v1/messages (that is T5), so there is no HTTP surface. I started no server and exercised the module and analyzer from plain python processes.

Setup
- Worktree `.../.claude/worktrees/003-t3`, HEAD `1a8143b`.
- `export PY=<repo>/.venv/bin/python PYTHONPATH=$PWD OPENAI_API_KEY=test-key AUTO_SIGNAL_LOG=1`.
- `$PY -c "import src; print(src.__file__)"` printed `<worktree>/src/__init__.py`.
- Scratch is `$TMPDIR/t3r3` (/tmp/claude-501/t3r3). The driver scripts are the round-2 ones (`run.py`, `driver.py`, `gen.py`, `synth.py`, `clamp.py`, `hostile.py`, `hostile2.py`), copied there. `run.py` monkeypatches `signal_log._log_path` to a scratch dir.
- Bodies are real `ClaudeMessagesRequest` objects, Claude Code shaped.
- The real `logs/` held only `proxy.log` before and after, with the same md5.

1. Directory mode (the round-2 repro)
- Command: `(umask 022; SCRATCH=$T/dm022 DRIVER=$T/driver.py $PY $T/run.py loop 1 d)`, then `stat -f '%Sp %N'`.

| Case | Directory | File |
|---|---|---|
| umask 022, fresh tree | `drwx------` (0700) | `-rw-------` (0600) |
| umask 077, fresh tree | `drwx------` | `-rw-------` |
| umask 000, fresh tree | `drwx------` | `-rw-------` |
| existing `logs/` at 0755, umask 022 | left at `drwxr-xr-x` (not tightened) | `-rw-------` |
| existing `logs/` at 0750 | left at `drwxr-x---` | not checked |

- Missing parent directories, using `SCRATCH=$T/mp/a/b` so that `mp`, `mp/a` and `mp/a/b` do not exist:
  - At umask 022, `mp`, `mp/a` and `mp/a/b` were created `drwxr-xr-x` (0755). Only the leaf `logs` was `drwx------`, and the file was `-rw-------`.
  - At umask 077 the parents came out 0700, which is just the umask.
  - This matches the expected behaviour: `makedirs(mode=)` applies to the leaf only (Python 3.7+), and parents keep the default mode.

2. Regression set (all PASS)
- 300 emits: `SCRATCH=$T/s1 ... loop 300 runA` gave 300 lines and 198,450 bytes, the same as round 2.
  - 0 lines failed the regex `^YYYY-MM-DD HH:MM:SS,mmm | AUTOSIGNAL {`, and all 300 parsed as JSON.
  - Leak grep counts were 0 for SECRETKEY, user_secret, "You are Claude", CLAUDE.md, claude-cli, tool_1, hmm, line2, system-reminder, "date 2026", runA-sess and "hello world".
  - The record has the same shape as round 2: `est_tokens` 13481, 8-hex `sid_hash` and `fm_hash`.
- Restart/append: a second process (`loop 100 runB`) took the file to 400 lines, and the first line was unchanged.
- Rotation: `AUTO_SIGNAL_LOG_MAX_BYTES=20000 AUTO_SIGNAL_LOG_BACKUP_COUNT=2`, 300 emits. Result: `auto_signal.log`, `.1` and `.2`, each 30 lines and 19,845 bytes, all `-rw-------`, with no `.3`.
- Concurrency: 4 background processes appended 200 emits each. Result: 800 lines, 0 unparseable.
- Disabled by default: with `AUTO_SIGNAL_LOG` unset, empty, `0` and `false`, no scratch dir or file was created, and the real `logs/` was unchanged.
- Unwritable path: a regular file where `logs/` should be gave rc 0 and 0 stderr bytes. A chmod 500 dir gave rc 0 and 0 stderr bytes.
- Symlink at the log path, pointing to `target/victim.txt` (`ORIG`): rc 0 and 0 stderr bytes. `victim.txt` still held `ORIG`, and the symlink was intact.
- Env clamps:
  - `BACKUP_COUNT=5000000 MAX_BYTES=99999999999999999999` gave `maxBytes 1073741824, backupCount 20`.
  - Three forced rollovers took 0.000 s each.
  - BACKUP_COUNT 20 and 21 both gave 20. MAX_BYTES 1073741824 and 1073741825 both gave 1073741824.
  - Invalid values `abc`, `0`, `-5` and empty gave rc 0 and empty stderr, 4 of 4.
- Huge ints: `max_tokens=10**5000` with `budget_tokens=10**5000` gave 1 line, `max_tokens` null, `think_budget` null and `think_type` "enabled". `True`, `1.5`, `-1`, `2**53` and `"9"` gave null. `2**53-1` was kept.
- Hostile names, in model, body fields, headers, `output_config` keys and `metadata` keys:
  - Names with a space, ESC, café, RLO, 65 x's, an empty string, a newline and `SECRET TEXT: hunter2` were all logged as `other`. The model value was `other`, and a 64-character name was kept.
  - The line was pure ASCII and contained none of hunter2, SECRET, ESC, evil, caf, space or break.
  - Legitimate names `anthropic-beta` and `x-custom_hdr.1` passed through.
  - The same held through `model_fields_set` on a real `ClaudeMessagesRequest`.
- `$PY -m pytest tests/test_signal_log.py -q` gave 53 passed.

3. Analyzer, including the new hash regex `[0-9a-f]{1,64}`
- Logs were generated through the real `emit_signal` with `gen.py` and `synth.py`, as in round 2. The figures are identical to round 2:

| Log | Measured | Verdict |
|---|---|---|
| 1 session, 3 turns | constancy 100.0% (1 of 1), shared 0.0% | insufficient sample (1 sessions, 1 with 2+ main-thread turns; need at least 10 of each) |
| 12 clean sessions, unique first messages, 3 turns each | constancy 100.0% (12 of 12 sessions, 36 turns), shared 0.0% (0 of 12) | `fm_hash is usable (thresholds met)` |
| 12 sessions, same first message | constancy 100.0% (12 of 12), shared 100.0% (12 of 12), top group sessions=12 | `fm_hash is NOT shown to be usable (thresholds not met)` |
| 12 sessions, first message changes per turn | constancy 0.0% (0 of 12), shared 0.0% | NOT shown to be usable |
| 9 clean sessions | constancy 100.0%, shared 0.0% | insufficient sample (9 sessions) |
| 12 sessions, 1 turn each | constancy n/a, shared 0.0% | insufficient sample (12 sessions, 0 with 2+ turns) |
| 1 session, 4 main-thread turns plus 1 subagent record | constancy 100.0% (1 of 1, 4 main-thread turns), subagent share 1 of 5 (20.0%) | insufficient sample |

  The all-records measure and the main-thread measure stay separate. All runs exited 0 with empty stderr.
- Empty file: rc 0, verdict "undetermined (no records with both hashes)".
- Garbage file (text, `AUTOSIGNAL not json`, `AUTOSIGNAL [1,2]`, binary bytes): rc 0, 0 tracebacks, records 0, 2 skipped.
- Rotated trio: files 3, records 90, skipped 0, rc 0.
- A missing path plus a valid file: warning on stderr, rc 0. No arguments: rc 2.
- Deep-nesting garbage (`'['*300000` and `'{"a":'*100000`): rc 0, 0 tracebacks, verdict "undetermined".
- ESC hash: I took the real `emit_signal` output and edited some records.
  - Edits: `fm_hash` set to `\x1b[31mRED` on every third record, `sid_hash` set to `ab\x1b]0;pwn\x07` on every fifth, plus `DEADBEEF` (uppercase), a 65-character hash, and a whole 3-record session with `fm_hash` `\x1b[31mTOP`.
  - Result: rc 0, 0 raw ESC bytes and 0 BEL bytes on stdout, and 0 ESC bytes on stderr. None of "TOP", "RED" or "DEADBEEF" appeared in the output. 39 records were parsed and 0 skipped. The bad-hash records were excluded from the hash statistics: verdict "insufficient sample (11 sessions, 6 with 2+ main-thread turns)" and sid_hash presence 79.5%.
- `_is_hash` boundaries:
  - Accepted: `a` and 64 zeros.
  - Rejected: 65 zeros, empty, uppercase, a non-hex letter, a trailing newline, a space, an int, None and a list.

Cleanliness
- `git status --short` shows only the untracked `factory/jobs/003-auto-model-groundwork-t3/rework.md`, `round-1/`, `round-2/` and `round-3/` (this file). `git diff --stat` is empty, so no tracked file was modified.
- The real `logs/` still holds only `proxy.log` (md5 unchanged). No server was started or left running. Nothing was blocked by the sandbox.
