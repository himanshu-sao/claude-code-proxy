VERDICT: CHANGES

One finding, low severity. The log DIRECTORY that `emit_signal` creates is 0755 (world-readable and traversable). The file inside is 0600. Everything else I ran passed, including all round-1 scenarios.

Scope: T3 is not wired into /v1/messages (that is T5), so there is no HTTP surface. No server was started and none is running. I exercised the module and the analyzer from plain python processes.

Setup (all from the worktree, commit 3bb73e1)
- `PY=/Users/himanshusao/Work/src/extra/himanshu-sao/claude-code-proxy/.venv/bin/python`, `PYTHONPATH=<worktree>`, `OPENAI_API_KEY=test-key`, `AUTO_SIGNAL_LOG=1`.
- `$PY -c "import src; print(src.__file__)"` printed `<worktree>/src/__init__.py`.
- Scratch: `$TMPDIR/t3r2` (/tmp/claude-501/t3r2). Driver scripts: `run.py`, `driver.py` and `synth.py` (the round-1 ones), plus `clamp.py`, `hostile.py`, `hostile2.py` and `gen.py`. `run.py` monkeypatches `signal_log._log_path` to a scratch dir. Bodies are real `ClaudeMessagesRequest` objects, Claude Code shaped (44 KB system prompt, 30 tools, a 7-message history with tool_use/tool_result rounds and thinking blocks, an injected `<system-reminder>`, adaptive thinking, output_config.effort, metadata.user_id, and x-api-key and session-id headers).
- The real `logs/` was never written. It held only `proxy.log` before and after.

A. Round-1 scenarios, re-run on the reworked code (all PASS)
- 300 emits: `SCRATCH=$T/s1 $PY $T/run.py loop 300 runA`. The file had 300 lines and 198,450 bytes. 0 lines failed the regex `^YYYY-MM-DD HH:MM:SS,mmm | AUTOSIGNAL {`, and all 300 parsed as JSON. Leak grep counts were 0 for SECRETKEY, user_secret, "You are Claude", CLAUDE.md, claude-cli, tool_1, hmm, line2, system-reminder, "date 2026" and the raw session ids. The record shape is unchanged: sorted `body_fields`, lowercased `header_names`, `est_tokens` 13481, 8-hex `sid_hash` and `fm_hash`.
- Restart/append: a second process (`loop 100 runB`) took the file to 400 lines. The first line was still the runA line, so nothing was truncated.
- Rotation: `AUTO_SIGNAL_LOG_MAX_BYTES=20000 AUTO_SIGNAL_LOG_BACKUP_COUNT=2`, 300 emits. Result: `auto_signal.log`, `.1` and `.2` with 30 lines and 19,845 bytes each, all 0600, and no `.3`.
- Invalid env (`abc`, `0`, `-5`, empty, used for both vars): 4 of 4 runs exited 0 with empty stderr.
- Concurrency: 4 processes appended 200 emits each to one file. Result: 800 lines, 0 unparseable.
- Unwritable path (a regular file where `logs/` should be): rc 0, no traceback. Read-only dir (chmod 500): rc 0, no traceback.
- Disabled by default: with the env unset, `AUTO_SIGNAL_LOG=` (empty), `0` and `false`, `emit_signal` left `logging.getLogger('auto_signal').handlers == []`. The real `logs/` was unchanged.
- Analyzer on empty, garbage (text, `AUTOSIGNAL not json`, `AUTOSIGNAL [1,2]`, binary bytes), the rotated trio (3 files, 90 records, 0 skipped), a missing path plus a valid file (warning on stderr, rc 0) and no args (usage, rc 2): all behaved as in round 1.
- Known-answer run, one session with 4 main turns plus 1 subagent record: main-thread-only constancy was 1 of 1 (100%), the all-records measure was 0 of 1 (0%), and the subagent share was 1 of 5 (20%). Correct, and the two measures stay separate.

B. New behaviours
1. File mode 0600: PASS. `stat` shows `-rw-------` on a freshly created log. The rotated `.1` and `.2` files are also `-rw-------`.
2. Directory not world-readable: FAIL (the one finding). With umask 022 and a fresh scratch tree, `SCRATCH=$T/dm $PY $T/run.py loop 1 d` gave `drwxr-xr-x .../dm/logs` and `-rw------- .../dm/logs/auto_signal.log`. `_ensure_handler` calls plain `os.makedirs(dirname, exist_ok=True)`, so the mode follows the umask (0755). The file contents are protected by 0600. Other local users can still list and traverse the directory, so they can see the file name, size and mtime. Suggested fix: `os.makedirs(dirname, mode=0o700, exist_ok=True)`. That affects only a directory the module creates. The pre-existing project `logs/` (0755, with a 0644 `proxy.log`) is not touched. Neither spec.md nor build.md promises a directory mode, so this is a gap against the task's expectation, not a spec violation.
3. Symlink at the log path: PASS. I linked `logs/auto_signal.log` to `target/victim.txt` (content `ORIG`) and ran `loop 3`. The result was rc 0 and 0 bytes on stderr. `victim.txt` still held `ORIG` (not followed, not appended to), and the symlink was left intact. A symlinked parent directory is still followed, and the file was created 0600 in the real directory. That is operator-owned and was not expected to be blocked.
4. Env clamps: PASS. Running `AUTO_SIGNAL_LOG_BACKUP_COUNT=5000000 AUTO_SIGNAL_LOG_MAX_BYTES=99999999999999999999` and reading the handler gave `maxBytes 1073741824, backupCount 20`. Three forced rollovers (`maxBytes` set to 1 on the handler) took 0.000, 0.001 and 0.001 s, against 28 s in the round-1 probe. The whole process ran in 0.06 s. Boundary values: BACKUP_COUNT 20 and 21 both give 20, and MAX_BYTES 1073741824 and 1073741825 both give 1073741824.
5. `max_tokens=10**5000` plus `budget_tokens=10**5000`: PASS. It yielded exactly 1 line with `max_tokens: null` and `think_budget: null`, and `think_type: "enabled"` was kept. Other `max_tokens` values: `True`, `1.5`, `-1`, `2**53` and `"9"` all gave null, and `2**53-1` was kept.
6. Hostile names: PASS. I used names with spaces, ESC (`\x1b[31m`), "café", RLO (U+202E), 65 x's, an empty string, a newline, and `SECRET TEXT: hunter2`, in `model`, body fields (via `model_fields_set` on a real `ClaudeMessagesRequest`, which allows extras), headers, `output_config` keys and `metadata` keys.
   - Every one was logged as `other`. A 64-character name is kept and a 65-character name becomes `other`.
   - The record was one line, pure ASCII, and contained none of "hunter2", ESC, "evil", "caf" or "space". The model value was `other`.
   - Legitimate names pass through, for example `anthropic-beta` and `x-custom_hdr.1`.
7. Analyzer on valid-JSON garbage: PASS. The file held a list-valued `sid_hash` and `fm_hash`, nested-list `body_fields`, mixed-type `header_names`, list and dict `req_class`, ESC in `reasoning_effort`, a dict `sid_hash`, scalar and null JSON payloads, and wrong-typed numeric fields. Result: rc 0, 0 tracebacks on stdout and stderr, 2 records parsed and 6 skipped, and all sections printed. A second file held `'['*300000` (open and balanced) and `'{"a":'*100000`. Result: rc 0, 0 tracebacks, 0 records, 3 skipped, verdict "undetermined".
8. Analyzer output is escaped: PASS. A record with `\u001b[31mRED` as a field name and `‮` in a header name produced 0 raw ESC bytes in stdout. The name printed as `'\x1b[31mRED'`.
9. Analyzer verdict, using synthetic logs generated through the real `emit_signal` (the thresholds line is printed every time: "constancy >= 95%, shared-session share <= 5%, with at least 10 sessions overall and 10 sessions with 2+ main-thread turns"):

| Log | Measured | Verdict | Expected |
|---|---|---|---|
| 1 session, 3 turns | constancy 100% (1 of 1), shared 0% | insufficient sample (1 sessions, 1 with 2+ main-thread turns; need at least 10 of each) | match |
| 12 sessions, unique first messages, 3 turns each | constancy 100% (12 of 12, 36 turns), shared 0% | usable (thresholds met) | match |
| 12 sessions, same first message | constancy 100%, shared 100% (12 of 12) | NOT shown to be usable (thresholds not met) | match |
| 12 sessions, first message changes every turn | constancy 0% (0 of 12), shared 0% | NOT shown to be usable | match |
| 9 clean sessions | constancy 100%, shared 0% | insufficient sample (9 sessions, 9 with 2+ turns) | match |
| 12 sessions, 1 turn each | constancy n/a, shared 0% | insufficient sample (12 sessions, 0 with 2+ main-thread turns) | match |

10. Regression check: `$PY -m pytest tests/test_signal_log.py -q` gave 50 passed.

Cleanliness
- `git status --short` shows only `?? factory/jobs/003-auto-model-groundwork-t3/round-1/`, which was untracked before I started, plus this file under `round-2/`. `git diff --stat` is empty. No tracked file was modified.
- The real `logs/` still holds only `proxy.log`. No server was started. Nothing was blocked by the sandbox.
