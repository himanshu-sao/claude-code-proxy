VERDICT: PASS

Scope: how `signal_log.emit_signal` is reached from the live `create_message` path (`src/api/endpoints.py:54-66`, call at `:122`) and the autouse fixture (`tests/test_endpoints.py:69-84`). All probes used FastAPI TestClient (no server, no port). The venv python imported `src` from the worktree (`.../003-t5/src/__init__.py`). Log files went only under `$TMPDIR/p5`. The real `logs/auto_signal.log` was never created: before and after the probes `logs/` held only `proxy.log`. No finding blocks the merge. Notes below are non-blocking.

1. Client-controlled input through the real Starlette `Headers` and request model (probe against `create_message`, `AUTO_SIGNAL_LOG=1`)
   - Hostile request sent: a model name `evil\nAUTOSIGNAL {"x":1}é‮AAAA…` (10 KB with an embedded newline), 305 headers, and duplicate `x-claude-code-session-id` headers (`a`, `b`).
   - The same request also had header names containing a quote or a space, a latin-1 non-ASCII header value, `x-claude-code-request-class: main\nINJECT`, extra body fields named `ex\nra`, `é` and a 500-character name, and a `metadata` key containing `\n`.
   - Result: exactly 1 physical line, 1072 bytes, with `model:"other"`. Hostile names became `other` in `body_fields`, `header_names`, `meta_keys` and `req_class`. `header_names` was capped at 50. The duplicate session id gave first-value-wins: `sid_hash` was `c64057dd`, which is sha256 of `sid:a`. No raw value, newline or non-ASCII character reached the file.
   - The earlier sweep sent a model name containing a NUL byte, a mixed-case alias and an emoji. Each produced one line and a 200 response.
   - Pre-existing and not T5's: T1's `logger.info(... model=%s ...)` at `endpoints.py:110-118` writes the raw `request.model`. My hostile name's newline plus a forged `AUTOSIGNAL {...}` text therefore appeared in `proxy.log` and the console, not in `auto_signal.log`. This is a log-forging vector in the existing proxy log, unchanged by T5. A follow-up could sanitise or `%r` the model there.
   - T5 adds no new route to the file. The `signal_log.py` input handling that T3's tests covered also holds through the real handler.

2. Denial of service and disk use (the call is synchronous on the event loop)
   - Order: FastAPI parses the body with pydantic, then runs `validate_api_key`, then runs the handler. The helper therefore runs only after auth and validation. No body-size limit exists in the app or in `uvicorn.run`. That gap is pre-existing, and the helper only adds linear work to it.
   - Measured on the TestClient path, helper time inline, medians:

     | Body | Helper time | Request total (log off to on) |
     |---|---|---|
     | ~8 KB typical (20 tools, 5 messages) | 0.09 ms (max 0.47) | 0.9 to 0.8 ms |
     | 2 MB single text | 7.9 ms | 6.8 to 14.0 ms |
     | 2 MB of tool definitions | 10.0 ms | 15.1 to 25.1 ms |
     | 1.85 MB, 30k messages | 6 ms | about 19 s either way |

   - The 1.85 MB, 30k-message case is dominated by the existing context trimming, which costs about 19 s of loop time whether or not the log is on. The helper's cost is small next to the handler's own work.
   - Rollover with `MAX_BYTES=200` and 20 backups, over 100 requests: helper median 1.28 ms, max 1.67 ms, 21 files. The loop is blocked for about 1 to 2 ms on a rollover.
   - Env clamps verified: `MAX_BYTES` of 99999999999999 clamps to 1073741824 and `BACKUP_COUNT` of 999999 clamps to 20.
   - Worst-case disk use is (20 backups + 1 live file) x 1 GiB = 21 GiB. That requires the operator to set both env vars to their maxima. The defaults give 4 x 5 MB = 20 MB. The bound depends on config, not on request count, so a client cannot exceed it. A single record is bounded at roughly 14 KB: `header_names`, `body_fields`, `oc_keys` and `meta_keys` are each capped at 50 entries of at most 64 characters, and all other fields are fixed-size. The measured record was about 1 KB.
   - Note: the default `HOST` is `0.0.0.0` (`config.py:38`) and `ANTHROPIC_API_KEY` is optional. With the key unset, any network peer can append bounded records. That is the same trust model as the rest of the proxy, and the log is opt-in.

3. Failing requests are logged once and leak nothing
   - Upstream 500 returned `{"detail":"Internal server error"}` with exactly 1 line. A 499 (patched `is_disconnected`) returned 499 with 1 line. The call is above conversion and the disconnect check, as the spec intends.
   - The record is built before any upstream or exception text exists. The DEBUG line from the guard contains `type(exc).__name__` only (`endpoints.py:65`). The upstream exception text (`secret upstream detail sk-123`) appears in the existing ERROR lines in `proxy.log`, which T5 did not change.

4. Authentication ordering (`config.anthropic_api_key = 'k'` set on the config object)
   - No key, wrong `x-api-key`, wrong Bearer, an Authorization header without `Bearer`, and an empty key all returned 401 with 0 log lines.
   - A good key with an invalid body returned 422 with 0 lines. A good key with a non-JSON body returned 422 with 0 lines. A bad key with a non-JSON body also returned 422 with 0 lines. The 422 for that last case is a pre-existing FastAPI body-versus-dependency ordering quirk, and nothing is logged in either case.
   - Good keys sent as `x-api-key` and as Bearer each logged exactly 1 line. The log is free of unauthenticated data when `ANTHROPIC_API_KEY` is set.

5. The autouse fixture
   - `delenv` plus a `_log_path` patch cannot be defeated by a developer `.env`. `load_dotenv(override=True)` runs only at `src` import, before any fixture. The fixture runs per test, and `monkeypatch` restores `AUTO_SIGNAL_LOG`, `_log_path` and `anthropic_api_key` on teardown. `reset_for_tests()` runs before and after, so the global `auto_signal` logger does not leak a handler into other modules. There is no `conftest.py`.
   - Empirical check: with `AUTO_SIGNAL_LOG=1` exported in the shell, I ran test_endpoints, test_signal_log, test_compat_endpoints, test_model_manager, test_effort_mapper and test_context_manager. Result: 239 passed, and `logs/` stayed `proxy.log` only. The local `.env` has no `AUTO_SIGNAL_LOG*` lines, so the dotenv case itself was not exercised. That is covered by the delenv and the reasoning above.
   - Residual: the fixture is module-scoped to `tests/test_endpoints.py`. Any future offline test in another module that POSTs `/v1/messages` through TestClient with the env on would write the real `logs/`. None exists today. `test_compat_endpoints.py` only touches unknown routes and `test_main.py` is live HTTP. If this recurs, move the fixture to `tests/conftest.py`.

6. The broad `except Exception` (`endpoints.py:64-65`)
   - It can only hide failures of the optional logging side effect: bad argument evaluation, or an exception escaping `emit_signal`. `emit_signal` swallows its own errors, and the helper has no security decisions, no auth and no routing.
   - The DEBUG text is a fixed prefix plus the exception class name. It carries no exception message and nothing attacker-controlled. It does not contain `reason=`.
   - Minor and non-security: at the default INFO level, a persistently failing write (disk full, bad permissions) is invisible to an operator who enabled the log. A one-time WARNING on first failure would help, but it is not required.
