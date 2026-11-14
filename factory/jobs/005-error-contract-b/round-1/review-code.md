VERDICT: PASS

- Correctness: src/core/config.py `_parse_stream_max_retries` matches spec (unset/blank -> 0 silently; non-int and negative -> 0 with one WARNING on logger `config`; valid honoured). `get_next_client_async(self, *, stream=False)` picks the budget correctly; sync getter untouched. (info)
- Tests: tests/test_config.py asserts real behaviour (client.max_retries values, warning count/logger/message, keyword-only TypeError, silent blank). Covers AC 1-8. In scratch copy of the branch: 390 passed, 4 xfailed, matching the 377 + 13 claim. (info)
- Docs: .env.example and README bullet match the spec's exact text and are placed after MAX_RETRIES; new env var is documented in both places per project convention. QUICKSTART not required by spec. (info)
- Shape: no lines over 100 chars in config.py or the new test; only the four listed files changed. (info)
- Minor/non-blocking: the warning logs the raw (unstripped) value via %r, which is fine. No bugs found.
