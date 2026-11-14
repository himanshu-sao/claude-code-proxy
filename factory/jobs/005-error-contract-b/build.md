# Build: 005-error-contract-b (STREAM_MAX_RETRIES)

Status: GREEN. Commit: 9485bb4 feat(config): add STREAM_MAX_RETRIES retry budget for streamed upstream calls on factory/005-error-contract-b.

## Changed
- src/core/config.py: Config.stream_max_retries (via _parse_stream_max_retries: unset/empty -> 0 silently; non-integer or negative -> 0 plus WARNING on logger config; valid honoured). get_next_client_async(self, *, stream: bool = False) uses stream_max_retries when stream, else max_retries. Sync get_next_client untouched.
- .env.example, README.md: exact doc lines from the spec, after the MAX_RETRIES entries.
- tests/test_config.py (new): 13 tests covering AC 1-8.
- Not touched: client.py, endpoints.py, existing tests.

## Commands and results (worktree, shared venv, OPENAI_API_KEY=test-key)
- venv import check printed the worktree src path.
- python -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider -q: 390 passed, 4 xfailed (377 baseline + 13 new). test_client_retries.py passes unmodified (AC 9).
- black -l 100 src/ tests/ and isort src/ tests/: clean.

## Mutation check (scratch copy in /tmp, deleted afterwards)
- Stream flag ignored: 2 failed, 11 passed.
- Selection inverted: 2 failed, 11 passed.
- Unmutated copy: 13 passed.

## Notes / not verified
- The job folder exists only untracked in the main checkout, so this build.md is written there and is not part of the commit.
- No live check: nothing calls get_next_client_async(stream=True) yet (slice C wires endpoints).
