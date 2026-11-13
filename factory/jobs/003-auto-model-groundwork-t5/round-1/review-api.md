VERDICT: PASS

Role: api-tester, behavioural verification, in-process only (no port bound, no uvicorn). I drove the real FastAPI app (`src.main:app`) with `fastapi.testclient.TestClient` (starlette 0.46.2, fastapi 0.115.13) from plain python processes. Everything below is what I observed, not what the spec predicts.

## Setup (exact)
- `OPENAI_API_KEY=test-key /Users/himanshusao/Work/src/extra/himanshu-sao/claude-code-proxy/.venv/bin/python -c "import src; print(src.__file__)"` printed `.../claude-code-proxy/.claude/worktrees/003-t5/src/__init__.py`, which is inside the worktree. Each harness also asserts this.
- Harness files are under `/tmp/claude-501/t5/` (`h.py` is shared, `c1.py` to `c8.py` are the checks), run as `.venv/bin/python -I cN.py`. Scratch logs are under `/tmp/claude-501/t5/scratch/`.
- Upstream is stubbed like `tests/test_endpoints.py`: `config.get_next_client` and `get_next_client_async` return a stub client, and `endpoints._write_last_model` records calls. `config.anthropic_api_key=None` except in check 4.
- The signal log is redirected by `signal_log._log_path = lambda: <scratch>` plus `signal_log.reset_for_tests()`.
- After all runs, `ls logs` in the worktree shows only `proxy.log`, and there is no `auto_signal.log`.

## (1) Claude Code-shaped requests (`c1.py`)
Request shape:
- 30 tools, a 30 KB system prompt (list form with `cache_control`), and `thinking:{type:adaptive}`.
- `output_config:{effort:high}` and `metadata.user_id`.
- 5 messages, including tool_use/tool_result turns, a `<system-reminder>` text block and a list-form tool_result.
- Headers `x-api-key`, `authorization`, `x-claude-code-session-id`, `anthropic-beta`, `x-claude-code-request-class: main`, and `anthropic-version`.
- Repeated header lines for `x-dup`, `anthropic-beta` and `x-claude-code-session-id` (the latter with a different second value).

Results:
- 3 models x stream/non-stream = 6 requests. Every one returned 200 and the file grew by exactly 1 line each time (6 lines). The `auto` flag was true only for `Claude-Proxy-Auto`, false for `claude-sonnet-4-5-20250929` and `claude-haiku-4-5-20251001`. The `stream` flag matched the request.
- `header_names` contains `x-api-key`, `authorization`, `x-claude-code-session-id`, `anthropic-beta`, `x-claude-code-request-class` and `x-dup`, each once.
- The record has `beta:true`, `sid:true`, `req_class:"main"`, `think_type:"adaptive"`, `oc_effort:"high"`, `oc_keys:["effort"]`, `tools:30`, `msgs:5`, `last_tool_result:true`, `fm_stripped:true`, `meta_keys:["user_id"]` and `est_tokens:9776`.
- With a repeated session-id header line, `sid_hash` was `f697127d`, which equals sha256("sid:SECRETSID-1234")[:8]. That is the first value. The second line's hash would be `6f2d5129`.
- The string `SECRET` (the prefix of every sentinel in header values, system, tool descriptions, tool inputs, tool results and prompt text) appears 0 times in the file. Literal text such as `fix the bug`, `Tool1` and `cmd` also appears 0 times.

## (2) 300 sequential requests, modes, latency (`c2.py`, logging silenced to ERROR for timing)
- 300 sequential requests with the log on (typical body 41 KB) gave exactly 300 lines, and all parse as JSON. File mode was `0600` and the directory (created by the handler) was `0700`. There was no backup file.
- Latency per request through TestClient, in ms. TestClient overhead is included and the stub upstream is instant, so it shows the delta rather than a production number.

| Case | ON median | ON p95 | OFF median | OFF p95 |
|---|---|---|---|---|
| Typical 41 KB, 300 sequential, ON then OFF | 0.91 | 1.15 | 0.78 | 1.00 |
| Typical 41 KB, 150 interleaved | 0.91 | 1.22 | 0.79 | 1.01 |
| ~2 MB (2,011,151 bytes), 40 interleaved | 5.62 | 6.25 | 5.49 | 6.05 |

- The delta is about 0.12 ms typical and about 0.13 ms for the 2 MB body. That is less than the 8-21 ms T3 estimate for 2 MB, because the 2 MB bulk is system text, which the record only counts. The 2 MB run gave 40 lines for 40 requests.
- Forced rollover with `AUTO_SIGNAL_LOG_MAX_BYTES=4000` and `BACKUP_COUNT=2`, 60 requests: files were `auto_signal.log`, `.1` and `.2`, all mode `0600`. The oldest lines were dropped past the backup count (12 retained). The maximum per-request latency across the rollover run was 1.78 ms (median 0.93 ms). Rollover blocks no longer than that in-process.

## (3) Failure cases against a log-off baseline (`c3.py`)
The baseline runs with `AUTO_SIGNAL_LOG` unset. "Same" means the same status and the same JSON body minus `id` (non-stream), or the same status and ordered SSE event types (stream). I ran alias and sonnet, non-stream and stream, for every case below. All 4 combinations were "same", all returned 200, and none returned 500.
- Regular file where the directory should be: the debug message was `signal_log: emit failed: FileExistsError`.
- Read-only directory (0500): `signal_log: write failed`.
- Existing read-only file (0400): `signal_log: write failed`.
- Symlink at the log path pointing at a nonexistent target: `signal_log: write failed`.
- `signal_log.emit_signal` patched to raise `RuntimeError`: the call-site guard logged `signal log skipped: RuntimeError`, and no file was created.
- `is_auto_alias` raising only when called from `_emit_signal_safe` (argument evaluation): `signal log skipped: RuntimeError`, the response matched the baseline, and `reason=` was still logged once.
- Hostile model names, log on versus off, stream and non-stream (every case: status identical to the baseline, same body or events, exactly 1 line, no 500): 5000 `x`, a name with an embedded newline plus `AUTOSIGNAL {"evil":1}`, `../../etc/passwd`, an RTL-override plus emoji name, a name that tries JSON injection (`', "auto": true, '`), a 70-char name, `claude-\x00nul`, `Claude-Proxy-Auto\n`, ` claude-proxy-auto` and the empty string.
  - The logged `model` is `other` for all of them except `../../etc/passwd`, which is logged verbatim because it matches the name regex `[A-Za-z0-9_.:/-]{1,64}`. That is harmless in a JSON string.
  - The line count equals the `AUTOSIGNAL ` marker count, so no injected extra line.
  - `Claude-Proxy-Auto\n` and ` claude-proxy-auto` are routed as the alias by T1 (`auto:true`, `reason=auto-placeholder`) while the logged model is `other`. That is consistent with T1's strip/lower matching and not a T5 defect.

## (4) 422 and auth (`c4.py`)
- With the log on, each of these returned 422 with 0 lines and no file or directory created: `reasoning_effort:"bogus"`, missing `messages`, `messages` as a string, `max_tokens` as a string, a top-level JSON list, malformed JSON, and `content-type: text/plain`. A valid request right after returned 200 and wrote 1 line.
- With `src.api.endpoints.config.anthropic_api_key='k'`:
  - A missing key, a wrong `x-api-key` and a wrong Bearer token each returned 401 `{"detail":"Invalid API key. Please provide a valid Anthropic API key."}`, wrote 0 lines and created no file.
  - The right `x-api-key` and the right Bearer token each returned 200 and wrote 1 line, 2 lines in total.
  - The key value `k` and the wrong value `WRONG` do not appear in the file.

## (5) Off values (`c4.py`)
- With `AUTO_SIGNAL_LOG` unset, empty, `0`, `false`, `False`, a space, `no`, `off` and `2`, stream and non-stream both returned 200. The file did not exist, its directory did not exist, and `logging.getLogger("auto_signal").handlers == []`.
- `1`, `true`, `TRUE`, `yes` and `on` each produced a line. (For `TRUE` the count read 2 only because it shares a scratch path with `true` on a case-insensitive filesystem. That is a harness artifact.)

## (6) Upstream raises (`c4.py`, stub raises `RuntimeError`)
- Alias and sonnet, non-stream: both returned 500 `{"detail":"Internal server error"}`, the same as the log-off baseline. There was exactly 1 line and 1 `.last_model` write.
- Alias and sonnet, stream: both returned 200 with the same SSE event types as the baseline. There was exactly 1 line and 1 `.last_model` write.
- The tracebacks in the output are the app's own error logging of the stub's exception.

## (7) T1 behaviours with the log on and off (`c7.py`)
For alias (non-stream and stream) and for `claude-3-opus-20240229` (non-stream and stream), both with the log on and with it off:
- Status 200.
- Exactly 1 `reason=` log record, an INFO record from the `proxy` logger. It was `auto-placeholder` for the alias and `tier-map` for opus.
- The response `model` echoed the requested name (non-stream body, stream `message_start`).
- `.last_model` was written exactly once, as `('big', 'stepfun-ai/step-5-preview')`, which equals `config.get_active_model("big")`.
- With `auto_model_enabled=False`, the lowercase alias logs `reason=tier-map` and the signal line has `auto:false`.

## (8) Analyzer (`c8.py`)
- I produced a log of 123 requests: 40 sessions-style requests x 3 models, mixed stream and request class, plus 3 hostile model names. It had 123 lines.
- `scripts/analyze_signal_log.py <file>` returned rc 0 with `records: 123, skipped invalid AUTOSIGNAL lines: 0`.
- A rolled set (4 files, MAX_BYTES 6000, BACKUP_COUNT 3) gave `records: 26, skipped invalid AUTOSIGNAL lines: 0`.

## Repo state
- `git status --short` in the worktree prints nothing, so it is clean. The only files differing from base 1765c8e are the intended `src/api/endpoints.py`, `tests/test_endpoints.py` and the job docs, plus this review file once written.
- Importing the app touches the gitignored `logs/proxy.log` (the app's normal proxy logger). That is pre-existing behaviour and unrelated to T5. `logs/auto_signal.log` was never created.

## UNVERIFIED (not observable without a real server)
- Real Claude Code header shapes through uvicorn/h11. TestClient (httpx) builds the repeated lines and header casing, so h11 parsing, header-order and merge behaviour for duplicate lines are untested.
- The real default `_log_path()` resolution to `<root>/logs/auto_signal.log` with a 0600 file and 0700 `logs/` directory in a running proxy. I always overrode `_log_path`. The 0600/0700 modes I observed came from the handler on my scratch paths.
- Event-loop latency under concurrent load. All timings are sequential and in-process with an instant stub upstream and TestClient overhead. The rollover cost was observed only sequentially (max 1.78 ms).
- Behaviour at uvicorn shutdown, and real client disconnects (the 499 path and its interplay with the call placed before the disconnect check).
- Real upstream errors (4xx/5xx from a provider). I used a stub that raises, not an HTTP upstream.
- A live-run repeat of "failing path leaves `/v1/messages` unchanged / 422 not logged / log unset creates no file" over a real socket. The in-process equivalents above all passed.
- Python 3.9 compatibility. I ran with the venv interpreter only.
