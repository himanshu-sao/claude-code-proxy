VERDICT: PASS

- Slice adds no HTTP route (config only), so the live check was startup and /health only.
- Setup: `git archive factory/005-error-contract-b` extracted to /tmp/claude-501/api-b/src. Started with `env -i`, using `uv run claude-code-proxy` on 127.0.0.1:8799. Port 8799 was verified free before each start. Env was OPENAI_API_KEY=test-key and OPENAI_BASE_URL=http://127.0.0.1:8798/v1, so no .env was loaded. Port 8082 was not touched.
- Results, one fresh proxy per case:

| STREAM_MAX_RETRIES | Startup | GET /health | Warning in log |
|---|---|---|---|
| unset | ok | 200 | none |
| "0" | ok | 200 | none |
| "2" | ok | 200 | none |
| "-1" | ok | 200 | `STREAM_MAX_RETRIES='-1' is negative; using 0` |
| "abc" | ok | 200 | `Invalid STREAM_MAX_RETRIES='abc'; using 0` |

- Cleanup: each listener (PIDs 79892, 80022, 80062, 80148, 80209) was killed by PID. A final lsof on 8799 and a pgrep for the scratch path both came back empty, so no server is left running.
- Not covered over HTTP: the `max_retries` value passed to the upstream client. It is only observable in code and is covered by tests/test_config.py.
