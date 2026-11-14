VERDICT: PASS

Scope note: T3 does not wire emit_signal into /v1/messages (that is T5), so there is no HTTP surface to hit. No server was started. I verified the module and analyzer from plain python processes instead.

Setup (all runs from the worktree):
- PY=~/Work/src/extra/himanshu-sao/claude-code-proxy/.venv/bin/python, PYTHONPATH=<worktree>, OPENAI_API_KEY=test-key, AUTO_SIGNAL_LOG=1.
- `python -c "import src; print(src.__file__)"` printed `<worktree>/src/__init__.py`.
- Driver scripts and scratch logs are under $TMPDIR/t3api/ (/tmp/claude-501/t3api), outside the repo.
- `_log_path` was monkeypatched to a scratch dir, as the tests do. A wrapper (run.py) did this via runpy.
- Bodies were real `ClaudeMessagesRequest` objects, Claude Code shaped. Each had a 44 KB system prompt, 30 tools with 300-char descriptions, a 7-message history (3 tool_use/tool_result rounds plus thinking blocks), and an injected `<system-reminder>` in the first user message. It also carried `thinking={"type":"adaptive"}`, `output_config.effort=high`, `metadata.user_id`, and the headers x-claude-code-session-id, anthropic-beta and x-api-key.

1. Append-only and one line per call
- `driver.py loop 300 runA` wrote 300 lines, 198,450 bytes, in one file.
- The awk check `^YYYY-MM-DD HH:MM:SS,mmm | AUTOSIGNAL {` found 0 non-matching lines of 300. Every line is `<timestamp> | AUTOSIGNAL {json}`.
- All 300 lines parsed as JSON. Tool inputs and tool_result text containing "\n" did not break the one-line format.
- Sample record: `body_fields` sorted, `header_names` lowercased and sorted, `est_tokens` 13481, `fm_hash` and `fm_stripped:true`, `oc_effort:"high"`, `oc_keys:["effort"]`, `think_type:"adaptive"`, `think_budget:null`, `last_tool_result:true`, `sid_hash` 8 hex chars, `tools` 30, `msgs` 7.
- Leak grep over the file for these strings found 0 occurrences of each: SECRETKEY, user_secret, "You are Claude", CLAUDE.md, the raw session ids, tool_1, "hmm", line2, system-reminder, "date 2026".
- Rotation: `AUTO_SIGNAL_LOG_MAX_BYTES=20000 AUTO_SIGNAL_LOG_BACKUP_COUNT=2`, 300 emits gave exactly `auto_signal.log`, `.1` and `.2` (19,845 bytes and 30 lines each). There was no `.3`. The newest 90 records are retained, and the older ones were dropped as expected.
- Invalid env: for `abc`, `0`, `-5` and empty, used for both vars, all four runs exited 0. The 4x50 emits went to one file of 200 lines with no rotation, so the 5 MB default is in effect.
- Four concurrent processes appending 200 each to one file gave 800 lines and 0 unparseable lines. There was no interleaving.
- Unwritable path (a regular file where the dir should be): `emit_signal` returned normally with no traceback on stderr.

2. Per-call cost
- Typical body (56 KB JSON, the shape above): median 0.091 ms and p90 0.105 ms over 200 calls, including the file write.
- 2 MB body (a 2 MB tool_result in the last message, 2,056,007 bytes JSON): first call 0.38 ms, median 0.10 ms, build-only 0.07 ms. This is cheap because `_block_chars` only takes `len()`.
- Worst cases I constructed, with 2 MB in the FIRST user message (median of 5 calls):
  - 2 MB plain text: 7.8 ms.
  - One 2 MB `<system-reminder>` block: 18.0 ms.
  - 55,000 closed reminders: 3.6 ms.
  - 115,000 unclosed `<system-reminder>` openers: 18.9 ms. There was no quadratic blowup.
  - 20,000 tool_use blocks (about 2 MB): 21.2 ms.
  - 2 MB base64 image: 0.03 ms.
  - 2 MB whitespace: 0.9 ms.
- Observation (not a defect): worst-case cost is about 20 ms, and it is synchronous in the caller (T5 will call it on the request path). That is acceptable for an opt-in diagnostic.

3. Restart
- The s1 file had 300 lines after process A. A second python process (`runB`, 100 emits) took it to 400 lines.
- The first line of the file was still the original runA line (timestamp 13:22:18,050), so the file was not truncated.

4. Analyzer
- Run on the rotated trio (`.log .log.1 .log.2`): 3 files, 90 records, 0 skipped, rc 0, all sections printed.
- Run on the 610-record s1 file (2 runs, same 7 first messages, different session ids): (a) reports "7 groups with more than 1 session; 14 of 15 sessions shared (93.3%)". That is correct: runA and runB share first messages. (b) reports 15 of 15 constant, and the verdict is "NOT shown to be usable". The figures match construction.
- Known-answer dataset 1 (3 sessions A/B/C, 2 turns each, all with first message "fix the bug" plus an injected reminder):
  - (a) 1 fm_hash group with 3 sessions, shared 3 of 3 (100%).
  - (b) 3 of 3 constant.
  - Verdict: NOT usable. Correct.
- Known-answer dataset 2 (one session with 4 main turns plus 1 subagent record with a different first message, agent-id and request-class headers):
  - Main-thread-only (b): 1 session, 1 constant (100%), distribution {1:1}.
  - All-records (b): 1 session, 0 constant (0%), distribution {2:1}.
  - (a) 0 shared. Subagent/auxiliary share is 1 of 5 (20%). Verdict: usable.
  - This is correct, and it shows the two measurements are separate.
- Empty file: rc 0, every section printed with "(none)" or "n/a", verdict "undetermined". The "n/a" and "(none)" markers are fine.
- Garbage file (text, `AUTOSIGNAL not json`, `AUTOSIGNAL [1,2]`, binary bytes): rc 0, "records: 0, skipped invalid AUTOSIGNAL lines: 2", verdict undetermined.
- Nonexistent path plus a valid file: stderr `warning: cannot read .../nope.log: [Errno 2] ...`, still processed 5 records, rc 0.
- No arguments: usage on stderr, rc 2.

5. AUTO_SIGNAL_LOG unset or falsy
- Env unset, a fresh process with the REAL `_log_path` (not monkeypatched): `emit_signal` left `logging.getLogger('auto_signal').handlers == []` (level 0, propagate True, so the logger was never configured).
- The same held for `AUTO_SIGNAL_LOG=0`, `false` and empty.
- The worktree's `logs/` contained only `proxy.log` before and after (1 entry both times). No `auto_signal.log` or other file was created.
- `git check-ignore -v logs/auto_signal.log` gives `.gitignore:179:logs/`.

Cleanliness
- `git status --short` is empty after the runs. Only ignored paths changed (.pytest_cache, __pycache__, and `logs/proxy.log` touched by importing src). The only file added by this review is this one.
- No server was started, so none is left running.
- Nothing was blocked by the sandbox.

No defects found. Minor notes only: the analyzer's "near 100%" and "near 0%" thresholds (95% and 5%) are the builder's choice, and the analyzer does not warn on binary garbage beyond counting skipped AUTOSIGNAL lines.
