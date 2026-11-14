VERDICT: PASS

Scope: the delta `git diff 3bb73e1 HEAD` (commit 1a8143b) in `src/core/signal_log.py`, `scripts/analyze_signal_log.py` and `tests/test_signal_log.py`. I used the venv python with `OPENAI_API_KEY=test-key`, and `src` resolves inside the worktree. All probes wrote only under `$TMPDIR/sec3`. The real `logs/` has no `auto_signal.log`. `pytest tests/test_signal_log.py` gives 53 passed. The delta adds no new dependency. It imports only stdlib `re`.

## 1. Log directory mode (`src/core/signal_log.py:361-363`)
- **Only a directory the module creates is affected: confirmed.** `os.makedirs(..., mode=0o700, exist_ok=True)` never chmods. Pre-existing directories at 0755, 0777 and 0700 were unchanged after `emit_signal`, and the file was still written. This protects the project's own `logs/` (0755, created by `src/core/logging.py`). The file stays 0600 through `_open` (:336-347), which is unchanged.
- **Umask.** A new leaf directory is always 0700 in practice:
  - umask 000 gives dir 0700, file 0600.
  - umask 077 gives dir 0700, file 0600.
  - umask 022 gives dir 0700, file 0600.
  - The umask can only remove bits, never add them, so no umask can make the leaf wider than 0700.
- **Missing parent: acceptable.** Only the leaf gets 0700. In the real layout the parent is the project root, which exists, so the parent case does not arise. In my probe (umask 000), a missing parent came out 0777, and at 022 it came out 0755. This is the interpreter's default behaviour for `makedirs`, not a regression. The parent holds nothing of ours. The only secret-bearing object is the file at 0600, inside the 0700 leaf. A non-root other user cannot traverse the leaf, and root is not a threat in this model. Accepting this is reasonable, and the comment at :361-362 states it. I do not require a change.
- **Symlinked directory.** `exist_ok=True` follows a symlink to an existing directory. Logs went into the target, and the target's mode (0755) was left alone. This needs the operator to plant the symlink in their own project tree, so it is not an attacker-reachable path. The file itself is still 0600 and `O_NOFOLLOW` applies to the final component only.
- **Dangling-symlink directory.** `makedirs` raises `FileExistsError` because the symlink is not a directory. The exception is swallowed by the `emit_signal` guard (:393). Nothing was created at the link target, nothing was raised to the caller, and no log was written. That is fail-closed.
- **Path component that is a regular file.** Handled without raising and with no logging.
- **Race between two creators.** 30 rounds with 8 threads each, all calling `makedirs(exist_ok=True)`, gave no error, and the final mode was 0700. Python's `makedirs` catches `FileExistsError` when the leaf is a directory. In-process creation is also serialised by `_lock`. If another process wins the race, the directory it made keeps whatever mode it chose and is not changed. That is the intended behaviour of never chmod-ing.

## 2. Analyzer hash handling (`scripts/analyze_signal_log.py:27, 166-167, 212`)
- **Hostile values: nothing reaches the terminal raw.** I fed 22 hostile `fm_hash` strings and 22 as `sid_hash`, each in records that would be grouped and printed if accepted. The analyzer exited 0, stderr was empty, and stdout contained no byte below 0x20 other than LF and no byte at or above 0x7f.
  - ESC CSI, OSC with BEL, and `\x9b` (C1 CSI)
  - RLO U+202E
  - an embedded newline, a trailing newline, a CR, and a fake `AUTOSIGNAL {}` after a newline
  - NUL
  - a 65-char string, and a 100000-char string
  - fullwidth `ａｂｃ`, Cyrillic `а` lookalikes, and an Arabic-indic digit `٠` / `٣`
  - uppercase hex `ABCDEF12`
  - leading and trailing space, `0x12`, the empty string, and a lone surrogate
  - All were rejected by `_is_hash`: the regex is `[0-9a-f]{1,64}` with `fullmatch`, so it does not match `$`-before-newline and has no ASCII-only gap, because the class is explicit. The result was "records with both hashes: 0", with the verdict "undetermined".
- **Raw bytes in the file.** I also tried a log line with a literal ESC byte and a literal RLO inside the JSON string, which is invalid JSON. It was skipped or rejected, with clean output. No raw byte reached the output.
- **The `ascii()` print at :212** is a second guard, and it is correct. `ascii(fm)[1:-1]` strips the quotes. It is dead code in practice, since only validated strings reach it, but harmless.
- **Regression check: legitimate hashes still pass.** I emitted 36 real records through `emit_signal` (12 sessions x 3 turns, with a session header and distinct opening prompts) into a scratch log. The module wrote 8-hex values such as `fm_hash:"cea71109"` and `sid_hash:"6d3cadbe"`. The analyzer counted 36 of 36 on both hashes. It gave 12 groups, 0% shared, 100% constancy over 12 sessions, and the verdict "usable (thresholds met)". So the key comparison is not zeroed by the stricter check. Boundary values also pass: 1 char, and 64 chars of `f` or `0`.
- **Caveat, non-blocking.** If someone later raises `_HASH_HEX_CHARS` above 64 or switches to uppercase or base64, the analyzer would silently reject every hash. The visible symptom would be "records with both hashes: 0 (excluded: N)", so it is not completely silent. A test that round-trips a real `emit_signal` record through `_is_hash` would pin this. That would be a nice addition, not a finding, because the new tests would not catch such a drift. I verified the round trip manually above.

## Findings
- None. No change required. The delta introduces no new injection, data-leak, unsafe-default or dependency issue, and the round-2 nit on raw `fm_hash` printing is closed.
