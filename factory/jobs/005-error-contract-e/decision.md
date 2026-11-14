APPROVE

Branch `factory/005-error-contract-e` @ 655f78a (cut from 1cff272). Approved for merge into `factory/005-error-contract`. The live provider check at the bottom is a precondition for restarting the proxy on :8082 with this code. It is not a precondition for the merge.

## Why
- All three round-1 reviews (security, code, api) end in a real `VERDICT: PASS` with evidence: PoCs, red/green and mutation runs, and a live fake-upstream table.
- I re-ran the suite in a `git archive` copy at /tmp/claude-501/approve-e/t. `src` resolved to the copy. The result was 592 passed on the venv python and 592 passed on /usr/bin/python3 (3.9.6), with 0 errors.
- (1) The whole-job blockers are fixed:
  - **3.9 errors:** the `hanging` fixture is now `async def`. Only that line and a comment changed, so no assertion was weakened.
  - **Truncated stream:** with no truthy `finish_reason` in any `choices[*]`, the client raises a mapped 502 (`api_error`, fixed message). It yields no `[DONE]` and reports no success, and the accounting call happens once. Live: a clean close mid-stream gives exactly one `event: error` and nothing after it. Zero chunks gives a real HTTP 502 with the Anthropic envelope. Normal finishes (`stop`, `tool_calls`, `length`, `content_filter`, with and without a usage chunk, with and without `[DONE]`) are unchanged.
  - **Lone surrogate:** it is replaced with U+FFFD once in the mapper, after redaction. Live: a non-stream 400 stays a 400 with a valid envelope (it was a 500). A mid-stream error frame gives one valid `event: error`.
  - **Empty text:** it now reads `Unexpected error: ReadError`, confirmed live on a mid-stream RST.
- (2) The reporting gap does not block approval.
  - The api review's live table does cover `finish_reason` null on every chunk plus `[DONE]` (case 4). It gives one truncation error and no `message_stop`. That is the accepted-risk case. It also covers `length` (3e, 3f) and `content_filter` (3i, 3j), which end normally. The security review's PoCs show the same result at the client layer.
  - Exhausted keys and client disconnect are in the api table too: 429 with an integer `Retry-After` and 0 upstream calls, and clean cancellation on both disconnect points. The gap is therefore smaller than the orchestrator note suggested.
  - Those two code paths are not touched by this diff. The diff touches only `create_chat_completion_stream`'s end-of-iteration handling, `errors.py`, and tests. The earlier whole-api.md already passed them live.
  - The one new interaction is that a disconnect must not be reported as truncation. The code review confirmed the cancel branch returns before the truncation check, and the security PoCs confirmed `active_requests` is cleaned up.
- (4) Scope is respected. The diff stat shows only README.md, src/core/client.py, src/core/errors.py, tests/test_endpoints_errors.py, tests/test_errors.py and the new tests/test_truncated_stream.py. `endpoints.py`, the converter, `config.py` and the byte-identical success test (`tests/test_midstream_errors.py`) are untouched. There are no new env vars, so `.env.example` needs no change.
- (3) The accepted risk is documented honestly, but only in the job files.
  - build.md, the test docstring and the user's own decision in answers.md all state that the SDK strips `[DONE]`, that a provider that omits `finish_reason` will show errors on good replies, and that no real provider was tested.
  - README.md:21 states the behaviour accurately ("including one that ends without a `finish_reason`") and makes no claim about Claude Code. It carries no warning for operators. The code reviewer rated that LOW. I agree it should not block, because the rework scoped README to one sentence and the user knowingly accepted the risk. The warning belongs in the backlog as a README/QUICKSTART troubleshooting note, and it should be added before this ships to other users.

## Before merging (orchestrator)
- Merge this branch into `factory/005-error-contract` as is. Do not edit the tree.
- Tell the user that six files changed, which is more than three, because this is a fix-up of reviewed slices.
- Merging into `feat/virtual-auto-model` follows the user's hands-free policy, since both suites are green on 3.14 and 3.9. Do not push, open a PR or merge into main.
- Do not restart the live proxy on :8082 on this code until the live check below is done.

## Live check the user must do before relying on this code
No real provider has been tested. The SDK strips a real `data: [DONE]` line, so a provider that never sends a non-null `finish_reason` fails every reply with "Upstream stream ended before a finish_reason was received". Run a scratch proxy on another port (for example `PORT=8799`) with the real `.env`. Send these to every tier model and every fallback model:
- a short text reply with `stream: true`
- a tool-call reply with `stream: true`
- a reply cut by `max_tokens` (expect `length`)
- a reasoning model with thinking on

Each must end with `message_stop` and no `event: error`. If any model fails, do not run this code against that model. Bring it back as a follow-up, for example a per-model opt-out. Also check how Claude Code displays the mid-stream `event: error` and the 502, because nobody has verified that.

## Non-blocking follow-ups for factory/backlog.md
1. Add a README/QUICKSTART troubleshooting line. A reply that ends with "Upstream stream ended before a finish_reason was received" means the provider omits `finish_reason`.
2. Provider behaviour is unproven. Run the live NVIDIA check above, and consider a per-model opt-out if any model omits `finish_reason`.
3. `_report_model_error` logs raw `str(exc)`. A lone surrogate there makes the logging handler print a `--- Logging error ---` block (seen in the api run). Sanitise it, together with the existing ESC/U+2028 item.
4. `map_upstream_error` calls `str(exc)` several times unguarded. Compute it once inside a try. This is pre-existing and not reachable from SDK exceptions.
5. The `Unexpected error: <TypeName>` fallback does not sanitise the class name. It is harmless, since the name is code-controlled.
6. A `finish_reason` on a non-first choice counts as a finish, but the converter reads only `choices[0]`. Such a stream would not be flagged. Decide whether to count only choice 0.
7. The `_empty()` / `StopAsyncIteration` branch in endpoints.py is unreachable with the real client. It is a dead-code candidate, to be handled with the items below.
8. The earlier out-of-scope items are still open: `convert_openai_streaming_to_claude` dead code, the unused `MappedError.retryable` and `counts_as_model_failure` fields, `str(e)` in `count_tokens` and `/test-connection` details, no total first-chunk deadline, and traceback logging of a chained cause.
9. The SDK stream object is not explicitly closed on disconnect or cancel (pre-existing, info). It is cleaned up by garbage collection.
