SIZE WARNING: 4 files (`src/core/config.py`, `.env.example`, `README.md`, `tests/test_config.py` new) and 11 acceptance criteria. Orchestrator to confirm with the user before build.

# Spec: 005-error-contract-b, STREAM_MAX_RETRIES

## Goal
Add a separate retry budget for streamed upstream calls. `STREAM_MAX_RETRIES` (default `0`) sets the OpenAI SDK `max_retries` only for streaming requests, so Claude Code's own retry loop handles transient failures before the first byte. `MAX_RETRIES` (default `2`) is unchanged for non-stream calls. Covers G14 and edge case 12.

## Approach
- **`src/core/config.py`**: in `Config.__init__`, right after `self.max_retries`, add `self.stream_max_retries`. Parse `STREAM_MAX_RETRIES` with its own rules (below). Change `get_next_client_async` only: add keyword-only `stream: bool = False` and pass `max_retries=self.stream_max_retries if stream else self.max_retries`. `get_next_client` (sync) is not changed.
- **`.env.example`**: one line after `MAX_RETRIES` (line 92).
- **`README.md`**: one bullet in "Environment Variables" > Performance, right after the `MAX_RETRIES` bullet (line 133).
- **`tests/test_config.py`** (new): config parsing and getter tests. Pattern follows `tests/test_client_retries.py` (`monkeypatch` env, `import src.core.config as cfg`, `cfg.Config()`). Use `caplog` for the warning.
- Do not touch `src/core/client.py` or `src/api/endpoints.py`. Do not edit the existing zero-argument stubs. The default call form `get_next_client_async()` stays valid.

## Interfaces
- Env var `STREAM_MAX_RETRIES`. Unset or empty (after strip) gives `0`, silently.
- `int(value.strip())`. Non-integer (for example `abc`, `1.5`, `true`) gives `0` and a WARNING on logger `config`, for example `Invalid STREAM_MAX_RETRIES=%r; using 0`. Startup does not fail. This differs from `MAX_RETRIES`, which raises on non-integers.
- Negative gives `0` and a WARNING on logger `config`, for example `STREAM_MAX_RETRIES=%r is negative; using 0`.
- `0` and positive integers are honoured as given (for example `2` gives `2`).
- Attribute: `Config.stream_max_retries: int`, always `>= 0`.
- `async def get_next_client_async(self, *, stream: bool = False)`. `stream=True` uses `stream_max_retries`. `stream=False` uses `max_retries`.
- `def get_next_client(self)`: unchanged.

## Doc text (exact)
`.env.example`, after the `MAX_RETRIES="2"` line:
```
STREAM_MAX_RETRIES="0" # Same as MAX_RETRIES but only for streamed upstream calls; default 0 lets Claude Code retry; non-integer or negative = 0 (with a warning)
```
README, after the `MAX_RETRIES` bullet:
```
- `STREAM_MAX_RETRIES` - Same as `MAX_RETRIES`, but only for streamed (`stream: true`) upstream calls (default: `0`). Keeping it at `0` lets Claude Code's own retry loop handle transient failures before the first byte. Non-integer or negative values fall back to `0` with a warning. `MAX_RETRIES` still applies to non-stream calls.
```

## Acceptance criteria
1. With `STREAM_MAX_RETRIES` unset, `Config().stream_max_retries == 0` and `MAX_RETRIES` is still `2`. (G14 default)
2. `STREAM_MAX_RETRIES="2"` gives `2`, and `"0"` gives `0`. (edge 12, non-zero honoured)
3. `STREAM_MAX_RETRIES="-1"` gives `0` and logs one WARNING on logger `config` that contains `STREAM_MAX_RETRIES`. (edge 12)
4. `STREAM_MAX_RETRIES="abc"` and `"1.5"` each give `0`, log one WARNING, and `Config()` does not raise. (edge 12)
5. With `MAX_RETRIES=4` and `STREAM_MAX_RETRIES=0`: `asyncio.run(cfg.get_next_client_async(stream=True)).client.max_retries == 0`, and the default call and `stream=False` both give `4`. (G14, non-stream unchanged)
6. With `STREAM_MAX_RETRIES=3` and `MAX_RETRIES=1`: stream gives `3`, non-stream gives `1`. (separation)
7. `cfg.get_next_client().client.max_retries == cfg.max_retries`, showing the sync getter is unchanged.
8. `get_next_client_async` accepts `stream` only as a keyword: `stream` as a positional argument raises `TypeError`.
9. `tests/test_client_retries.py` passes unmodified.
10. `.env.example` contains the exact `STREAM_MAX_RETRIES="0"` line from the doc text above, and README "Environment Variables" contains the exact `STREAM_MAX_RETRIES` bullet above.
11. Offline gate, run from the job worktree: `OPENAI_API_KEY=test-key .venv/bin/python -m pytest tests/ --ignore=tests/test_main.py -p no:cacheprovider` passes with 377 baseline tests plus the new ones, and 4 xfailed. Then `.venv/bin/python -m black src/ && .venv/bin/python -m isort src/` is clean (line length 100). Only the four files listed above change.
