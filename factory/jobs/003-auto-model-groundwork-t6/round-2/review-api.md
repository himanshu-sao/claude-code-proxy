VERDICT: PASS

Round 2 run-the-docs review of the reworked T6 docs (rework commit ae1ae5b, base 11b8f2a). No port was bound and no uvicorn was started (the user declined local port binding), so nothing here is BLOCKED. Server-only items are under UNVERIFIED. Every reworked statement I could execute matched what I observed, except one cosmetic nit (N1) that does not block a merge.

Setup
- Worktree: /Users/himanshusao/Work/src/extra/himanshu-sao/claude-code-proxy/.claude/worktrees/003-t6.
- Python: the venv python (3.14), used in place of the docs' `python3` and `uv run`. `OPENAI_API_KEY=test-key`.
- Scratch files only under $TMPDIR (/tmp/claude-501/...). The real logs/auto_signal.log was never created: `ls logs` shows only proxy.log. The tracked model_contexts_cache.json is unchanged (sha1 54271441ec43016e1a484114c0de8f853ffa59cd before and after).
- `python -c "import src; print(src.__file__)"` resolves to the worktree's src/__init__.py.

(1) Open-proxy guidance. Observed via fastapi TestClient on the real app, with a stub upstream client and no real upstream call.
- Routes: only POST /v1/messages (endpoints.py:98-100) and POST /v1/messages/count_tokens (:208-209) take `Depends(validate_api_key)`. /health (:246), /test-connection (:290), /v1/models (:330) and / (:404) do not. `validate_api_key` returns immediately when `config.anthropic_api_key` is falsy (:87).
- Command: `python $TMPDIR/t1.py`. It sets `src.api.endpoints.config.anthropic_api_key` to None, then to a private test value, and sends 4 header variants (none, wrong x-api-key, wrong Bearer, correct key) to each of the 6 routes.
- Key unset: all 24 requests returned 200. POST /v1/messages and count_tokens (the latter returned {"input_tokens":1}) both worked with no key and with a wrong key. This confirms "no key needed when ANTHROPIC_API_KEY is unset".
- Key set:
  - POST /v1/messages with no key, a wrong x-api-key or a wrong Bearer returned 401 `{"detail":"Invalid API key. Please provide a valid Anthropic API key."}`. The correct key returned 200.
  - POST /v1/messages/count_tokens behaved the same: 401 for no or wrong key, 200 with the correct key.
  - GET /health, /v1/models, /test-connection and / returned 200 with no key and with a wrong key. The README sentence "a key only protects POST /v1/messages and /v1/messages/count_tokens; the other four never check it" is correct.
- `.env` override (HOST). src/__init__.py is `load_dotenv(override=True)`. Run in a scratch directory containing a .env with HOST set to 127.0.0.1:
  - Command: `cd $TMPDIR/envtest && HOST=9.9.9.9 PYTHONPATH=<worktree> python -c "import os, src; print(os.environ['HOST'])"`. Output: `127.0.0.1`. The .env value beat the shell value.
  - Control, same command in a directory with no .env: `9.9.9.9`. So `HOST=127.0.0.1 ./start.sh` is overridden when .env sets HOST, as the README says.
  - A cwd-based .env lookup is what python-dotenv's find_dotenv does when invoked from a script. A copy of src/__init__.py plus a script run in a scratch tree also gave HOST = 127.0.0.1 with the shell value 9.9.9.9.
  - src/core/config.py:38 reads `HOST` with default "0.0.0.0", matching "HOST defaults to 0.0.0.0".
- .env.example ships `ANTHROPIC_API_KEY="your-expected-anthropic-api-key"` (line 6, uncommented) and `HOST="0.0.0.0"` (line 73, uncommented), exactly as the README and the new .env.example warning (lines 58-63) say. The README's claim that copying the placeholder verbatim turns validation on is consistent with the key-set run above (validation is keyed on any non-empty value).

(2) Retention. Run against src.core.signal_log with `_log_path` pointed at a scratch dir (`python $TMPDIR/ret.py $TMPDIR/ret <worktree>`).
- Handler open, then the file deleted while the process runs: after the first emit the file existed (483 bytes). I deleted it with os.unlink, then emitted again. Result: the file did NOT reappear on disk and the logs dir stayed empty. The handler's still-open fd showed the same inode, link count 0, size 966 (both records), so the process keeps writing to the unlinked file. This matches the README's "deleting it while it runs leaves the proxy writing to an unlinked file" and the "turn it off and restart FIRST" order.
- Switching AUTO_SIGNAL_LOG to off in the same process stopped further writes (size stayed 966), but the handler and the unlinked inode stay held until the process exits, so a restart is still needed to release the disk space.
- Fresh process, files deleted, AUTO_SIGNAL_LOG=off, three emits: `files: []`. Nothing is created.
- Worst case arithmetic: `_int_env` clamps 99999999999 to 1073741824 and 99 to 20, so 21 x 1 GiB = 21.0 GiB, matching "up to 21 files x 1 GiB, about 21 GiB".
- Rollover count (`python $TMPDIR/roll.py ...`, 300 records, MAX_BYTES=1000):
  - BACKUP_COUNT=20: handler.backupCount 20, 21 files on disk (log plus .1 to .20), largest file 936 bytes (each at most MAX_BYTES).
  - BACKUP_COUNT=999 (clamped to 20): also 21 files.
  - BACKUP_COUNT=3: 4 files.
  - So "(BACKUP_COUNT + 1) x MAX_BYTES" is correct.

(3) Umask sentence.
- Existing directory (created 0755), file mode produced by the real handler (`python $TMPDIR/um_pre.py`): umask 022 -> 0600, 077 -> 0600, 277 -> 0600, 377 -> 0600. The file is exactly 0600 whatever the umask, so "where fchmod exists the file mode is forced to exactly 0600 regardless of umask" is correct.
- Module creates the directory (parent exists, logs/ missing; `python $TMPDIR/um.py`):
  - umask 022 -> dir 0700, file 0600.
  - umask 077 -> dir 0700, file 0600.
  - umask 277 -> dir 0500, file NOT WRITTEN, with no exception reaching the caller.
  - umask 377 -> dir 0400, file NOT WRITTEN, with no exception reaching the caller.
  The README's "(for example 0277) it could come out non-writable and writes would be silently skipped" is confirmed. I did not turn on DEBUG logging to see the message, so "visible only at DEBUG" rests on `handleError` in signal_log.py (it logs at DEBUG only).

(4) Disabled-alias rule, real ModelManager, mapped model for each name (BIG = the configured big model):
- AUTO_MODEL_ENABLED off: `claude-proxy-auto`, `my-auto`, `fast-auto`, `GPT-auto`, `my-opus-auto` all give (BIG, tier big). `gpt-auto`, `o1-auto`, `ep-auto`, `doubao-auto`, `deepseek-auto` pass through unchanged with tier `unknown`. Extras: `x-haiku-auto` -> small, `X-SONNET-auto` -> middle, `my-OPUS-auto` -> big (case-insensitive substring), and `gpt-opus-auto` -> pass-through (the prefix is checked first).
- AUTO_MODEL_ENABLED on: the same results, and `is_auto_alias` is True only for `claude-proxy-auto`.
- Every row matches the README sentence word for word: the prefixes `gpt-`, `o1-`, `ep-`, `doubao-`, `deepseek-` are case-sensitive and checked first, then haiku/sonnet/opus case-insensitively, then everything else (including the default alias, `my-auto`, `GPT-auto`) goes to BIG. `doubao-` is present in model_manager.py (line 32 region). The alias-row wording "checked first, before every other row" is right: `is_auto_alias` is the first check.

(5) Analyzer glob. Scratch dir with a copy of scripts/analyze_signal_log.py, `zsh -c` and `bash -c` running `python scripts/analyze_signal_log.py logs/auto_signal.log*`:
- No log present: zsh prints `zsh:1: no matches found: logs/auto_signal.log*` and exits 1, and python never runs. bash passes the literal pattern; the script prints `warning: cannot read logs/auto_signal.log*: [Errno 2] ...`, prints a summary with `files: 1, records: 0`, and exits 0.
- Log present (empty file): both shells expand the glob and the script prints the summary, `Verdict: fm_hash is undetermined (no records with both hashes)`, exit 0.
- Quoted glob (bash, log present): the script gets the literal pattern, reports the same warning and "files: 1, records: 0". So the README is right not to say "quote the glob".
- The README's new sentence ("the shell expands the glob (the script does not), so run it after the log exists: zsh stops with 'no matches found' otherwise, while bash passes the pattern through and the script warns about a missing file and exits 0") is accurate for both shells.

(6) model_contexts_cache.json creation. Scratch directory $TMPDIR/ctxtest (empty), cwd there, PYTHONPATH the worktree, real `run_discovery_and_patch(base_url="http://dead-upstream.invalid", ...)`:
- Before: no model_contexts_cache.json. The upstream call was refused by the sandbox network filter (a dead upstream, as intended); the function still completed.
- After: a 685-byte model_contexts_cache.json existed in that scratch cwd, holding fallback [32000, 4096] entries for the configured models. The tracked file in the worktree was untouched. This confirms "if none exists there, the proxy creates one in that directory at startup" (the startup hook in main.py calls this function).

(7) Tests and tooling (venv python, worktree cwd):
- Five-file offline suite: `214 passed`. `tests/ --ignore=tests/test_main.py`: `239 passed`. Old three-file command: `111 passed`.
- The README (lines 376-388) and QUICKSTART (63-70) use the same three commands, say "(214 tests)" and "(239 tests)", and note the counts "are the current numbers and will change". The 111 figure is not in the docs.
- AUTO_* parity loop (`for v in $(grep -rhoE 'AUTO_[A-Z_]+' src | sort -u); ...` against .env.example and README.md): no MISSING output.
- `python -m black --check -l 100 src/`: 17 files left unchanged. `python -m isort --check src/`: clean.
- AST of src/conversion/effort_mapper.py at 11b8f2a versus HEAD, docstrings stripped: identical (the raw text differs only by docstrings).
- `git diff --stat 11b8f2a HEAD -- . ':!factory'` lists only .env.example, QUICKSTART.md, README.md and src/conversion/effort_mapper.py.
- Greps for the removed wording: no "job 004", "later job", "used to return" or "live suite was not run here" remain in README, QUICKSTART or .env.example.
- `git status --short` shows only untracked review files under factory/jobs/003-auto-model-groundwork-t6/ (round-1/review-security.md and this round-2/ review). No tracked file modified.

Nits (non-blocking)
- N1. README.md line 310 now reads `A top-level reasoning_effort: "max" is accepted .` with a stray space before the period, left over from removing the parenthetical.
- N2. The Python docstrings/comments in src/core/signal_log.py (lines 1, 246), src/api/endpoints.py (lines 55, 120) and tests/test_signal_log.py:1 still say "content-free", which the docs now avoid. Not a user-facing doc and not in this round's scope.

UNVERIFIED (needs a real server; none run)
- Any live HTTP behaviour (uvicorn, start.sh and how it passes HOST, real sockets, the startup hook actually firing in a running process).
- The on-disk modes of a logs/ directory created by src/core/logging.py in a running proxy.
- That a real shell-exported HOST is ignored by `./start.sh` end to end (shown here only at the python-import level).
- That the DEBUG message appears for a silently skipped write under umask 0277 (code read only).
- The real Claude Code settings and request shape, the 262,144 / 32,768 context figures, `uv run` command forms, and the live `pytest tests/` including tests/test_main.py, all listed by the README as NOT verified.
