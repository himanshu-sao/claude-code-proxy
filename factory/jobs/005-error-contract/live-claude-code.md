VERDICT: PASS

Every case behaved as the error contract intends, with one caveat on cases 7 and 8 (see the notes under the table).

## Setup

- CLI: `/Users/himanshusao/.local/bin/claude`, version `2.1.323 (Claude Code)`.
- Invocation: `claude -p "Reply with the single word hello" --output-format json|text < /dev/null` run from the scratch directory `/tmp/claude-501/cc-live/work/`.
- Environment for each run: `ANTHROPIC_BASE_URL=http://127.0.0.1:8794 ANTHROPIC_API_KEY=fake-client-key CLAUDE_CODE_MAX_RETRIES=2`.
- Two additions to the requested command:
  - `CLAUDE_CONFIG_DIR=/tmp/claude-501/cc-live/cfg`, an empty scratch config directory.
  - `< /dev/null` to silence the stdin warning.
  - Each run was wrapped in `timeout 150`.
- Proxy: `git archive feat/virtual-auto-model` (39cba93) extracted to `/tmp/claude-501/cc-live/copy/`.
  - Started with `env -i`, MAX_RETRIES=0, two fake keys, no ANTHROPIC_API_KEY.
  - `src` resolved to the copy (`/private/tmp/claude-501/cc-live/copy/src/__init__.py`).
- Fake upstream: `/tmp/claude-501/cc-live/fake/fake.py`, one fresh fake plus proxy pair per case on ports 8793 (fake) and 8794 (proxy). Both ports were checked free before each start. The PID that owned each port was confirmed, then killed after the run.
- Port 8082 was never touched.
- Scripts and raw logs: `/tmp/claude-501/cc-live/fake/run.sh` and `c*.log`, `c*.out`, `c*.proxy.log` in the same directory.
- Counts below are the fake upstream's count of POSTs to `/v1/chat/completions`, which is the authoritative figure. The proxy request count from `grep "proxy | Request ["` also counts the "failed" lines, so I did not use it. Proxy-side requests visible in its log: case 1 = 1, case 2 = 1, case 3 = 2, case 4 = 2, case 5 = 3, case 6 = 3, cases 7 and 8 = 2, case 9 = 1.

## Results

| # | Case | CLI exit | Time | CLI output (json `result` / text, same in both formats) | Upstream calls |
|---|------|----------|------|------|------|
| 1 | Success (finish_reason stop) | 0 | 1 s | `hello`, is_error false | 1 (stream) |
| 2 | Upstream 400 "fake bad request from upstream" | 1 | 1 s | `API Error: 400 fake bad request from upstream` (api_error_status 400, terminal_reason api_error) | 1, no retry |
| 3 | 429 with `Retry-After: 5`, then success | 0 | 6 s | `hello`. The CLI waited about 5 s: calls at 12:08:04 and 12:08:09. | 2 |
| 4 | 429 without Retry-After, then success | 0 | 1 s | `hello`. The retry came immediately, within the same second. | 2 |
| 5 | 503 twice, then success | 0 | 2 s | `hello`. The CLI retried with short backoff, 12:08:29 / :30 / :31. | 3 |
| 6 | 503 on every request | 1 | 2 s | `API Error: 503 fake unavailable. This is a server-side issue, usually temporary — try again in a moment. If it persists, check your inference gateway (127.0.0.1:8794).` (api_error_status 503) | 3 (the original plus 2 retries, matching CLAUDE_CODE_MAX_RETRIES=2) |
| 7 | Mid-stream failure ("hel", "lo", then the connection is cut) | 0 | 1 s | `hello`. The proxy logged `Mid-stream upstream error: status=500 type=api_error`. | 2 (stream, then a non-stream re-send) |
| 8 | Truncated stream (two chunks, clean close, no finish_reason, no `[DONE]`) | 0 | 1 s | `hello`. The proxy logged `Upstream stream ended before a finish_reason was received (status=502)` and then `Mid-stream upstream error: status=502`. | 2 (stream, then a non-stream re-send) |
| 9 | 400 "This model's maximum context length is 8192 tokens" | 1 | 1 s | `Prompt is too long · this conversation is a single exchange and cannot be compacted — the request size comes mostly from system prompt, tool definitions, or attachments.` (api_error_status 400, terminal_reason prompt_too_long) | 1, no retry |

Notes:
- Case 1 also ran in text format, as part of an earlier setup check. It printed hello.
- In cases 7 and 8 the CLI did not show a fake success from the broken stream. It saw the `event: error`, discarded the partial "hel" and "lo", and re-sent the same request non-streaming. My fake answers non-stream requests with a normal `hello`, so that retry succeeded and the final output is `hello`. The visible text is therefore from the clean second response, and no partial text leaked.
- In case 9 the CLI recognised the prompt-too-long error and mapped it to its own "Prompt is too long" message. It did not retry and did not shrink the request. With a one-exchange conversation there was nothing to compact, so compaction with a longer conversation was not exercised. The upstream's original wording ("maximum context length is 8192 tokens") is not shown.

## Not observed

- What the CLI shows in cases 7 and 8 when the non-stream fallback also fails. My fake always answered the non-stream request. I did not run a variant where it fails too.
- Whether the proxy's `capability_rejected: prompt_too_long ` prefix reaches the CLI. The CLI replaces the text with its own message, so it cannot be seen from the CLI output.
- Case 9 with a long multi-turn conversation, where the CLI might auto-compact and retry with a smaller request.
- Partial text rendering in an interactive session. Only `-p` mode (json and text) was used.
- Case 4: whether the CLI adds a small delay on a 429 without Retry-After. It was under 1 s at the resolution of the log timestamps.
- Case 3 under `CLAUDE_CODE_MAX_RETRIES` set to other values.
- Any behaviour with a real provider or real Anthropic client-key validation. The proxy was run with ANTHROPIC_API_KEY unset.
