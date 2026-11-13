VERDICT: PASS

Scope: rework commit 3bb73e1 (`git diff be153c8 HEAD`): `src/core/signal_log.py`, `scripts/analyze_signal_log.py`, `tests/test_signal_log.py`. I probed with the venv python, `OPENAI_API_KEY=test-key`, and `src` resolving inside the worktree. Everything was written under `$TMPDIR/sec2`. The real `logs/` still has only `proxy.log`. `pytest tests/test_signal_log.py` gives 50 passed. There are no new dependencies and no eval, pickle or subprocess in the module or script.

## Round-1 findings, each verified by reading and by probe
1. **Names filter: FIXED.** `_safe_name` (signal_log.py:91-95) and `_names` (:98-99) feed `body_fields` (:264), `header_names` (:265), `model` (:266), `oc_keys` (:290) and `meta_keys` (:317). I probed a plain dict and a real `ClaudeMessagesRequest` (extra="allow") carrying these hostile names. All of them came out as `"other"`:
   - a model with spaces
   - keys containing spaces, ESC, `é`, RLO, an empty string, or 65 and 70 characters
   - a header named `X-Bad Name`
   Identifier-shaped names pass through unchanged. Header values and metadata values never appear. The cap of 50 per list holds with 100k extra fields (0.04 s). A non-str name goes through `fullmatch` as `"other"` without raising.
2. **Permissions and symlink: FIXED.** `_SignalFileHandler._open` (:336-347) opens with `O_NOFOLLOW`, mode 0600, then `fchmod(0600)`.
   - A new file was 0600.
   - A pre-existing 0644 file was tightened to 0600, and the old content was preserved and appended to.
   - A symlink at the log path was not followed. The target stayed `'T\n'` and no exception reached the caller.
   - A dangling symlink did not create its target.
   - Rotated files (`.1`, `.2`) were all 0600, including when the base file started as 0644.
   - Failure only goes through `handleError` to a DEBUG message.
   - The fd is closed on failure. I found no TOCTOU, because `os.open` is atomic with respect to the symlink and the mode.
3. **Env clamps: FIXED.** `_int_env` (:62-70) with `_MAX_BACKUP_COUNT=20` and `_MAX_MAX_BYTES=1 GiB` (:30-31). With `BACKUP_COUNT=5000000` and `MAX_BYTES=99999999999999999999` the handler showed 20 and 1073741824. `-5`, `0`, `abc`, `1e3`, a non-ASCII-digit string `٣`, `nan` and a 5000-digit string all fell back to the default of 3. A 5000-digit string does not raise (the ValueError is caught). `"  7 "` gives 7.
4. **Huge and odd ints: FIXED.** `_small_int` (:102-106) returns None for bool, float, negative, `>=2**53`, str, None and NaN. A 5000-digit int in the `max_tokens` position and a `budget_tokens` of `2**70` or `2**60` no longer drop the record (null fields, record emitted). `2**53-1` passes. My probe harness itself failed on `repr(10**5000)`, which is a harness artefact and not a product bug.
5. **Analyzer: FIXED, with one residual nit (below).** I ran a hostile log with ESC and OSC sequences, RLO, nested lists and dicts as names, list and dict values for `sid_hash`, `fm_hash` and `req_class`, `[`x300000, `{"a":`x100000, a 6000-digit integer and 5000-char hashes. It exited 0 with empty stderr, and stdout contained no control byte and no RLO character. Names and enum values go through `ascii()` (analyze:91, :120, :146). `_is_hash` (:164-165) requires a non-empty str, and `RecursionError` is caught (:44).

## New problems introduced by the rework
- None blocking. The rework introduced no new injection, DoS or data-leak path. `ascii()` on enum values is safe. The new verdict text prints only constants and counts.
- **Nit, non-blocking (analyze_signal_log.py:164-165, :210).** `_is_hash` accepts any non-empty str, and `fm_hash` is printed raw at :210 (`top group fm_hash=%s`). I confirmed that a hand-crafted log line with `fm_hash:"\x1b[31mEVIL"` reaches the terminal as a raw ESC. The proxy only ever writes 8 lowercase hex, so this needs someone who can write to the 0600 log, or an analyzer pointed at a foreign file. Optional fix: `_is_hash = re.fullmatch(r"[0-9a-f]{1,64}", v)`, or print `ascii(fm)`. I am not asking for another round over this.

## Judgement: should unknown names collapse to "other" via an allow-list?
**Recommendation: keep the identifier-shape filter as it is. Do not add an allow-list of known Claude fields and headers. Do not change the length cap.**
- **Threat model.** Three conditions are met:
  - The only party who can put text into these names is the client, which is Claude Code on the operator's own machine. A stray API caller is possible, but the proxy is unauthenticated and local by design.
  - The only reader is the operator, through a file that is now 0600, gitignored, rotated, and capped at 1 GiB x 21 files and 50 entries per list. Nothing in the log is returned to any client or sent upstream.
  - What can get in is at most 64 identifier-shaped characters per name. That can't carry prose, a prompt or a key (the filter bars spaces, quotes, `=`, `+` and non-ASCII) and cannot break a line (`ensure_ascii` is also on).
  A hostile client therefore writes a short token into a private file that the operator already controls. That is not a confidentiality leak. It is a bounded, operator-visible diagnostic note. The spec's "content-free" promise is met in substance, because there is no user content, no values and no free text.
- **Cost of the allow-list.** Phase 0's purpose is to discover which unknown body fields, headers, `output_config` keys and metadata keys Claude Code sends, such as a new `x-claude-code-*` header or a new `output_config` key. An allow-list would turn every one of those into `"other"`. The analyzer would only report that something unknown exists and could not say what, and each Claude Code release would require a code edit before you could see it. That defeats the experiment.
- **Residual risk and how to bound it.** The one realistic worry is an identifier-shaped secret, for example a client that puts a key-like string in `model` or a metadata key. That is not how Claude Code behaves. If you want a cheap extra step later, add a rule that rejects names with no separator that are 32 or more characters of hex or base64, and collapse those to `"other"`. I do not think that is needed for this job.
- **Possible compromise, not required.** Apply an allow-list only to `model`, because the operator knows the model names, and keep the open filter for the four name lists. I do not recommend it for T3, because `model` as an unknown value is also useful for the auto-alias work.

## Notes for wiring (T5), unchanged from round 1
- `emit_signal` does blocking file I/O on the event loop. Call it after request validation and offload it if practical.
- The fm_hash verdict (8 hex, unsalted) is acceptable for this capture now that the file is 0600. It must not carry over to job 004.
