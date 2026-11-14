# Quick Start Guide

Get Claude Code talking to any OpenAI-compatible provider in under 2 minutes.

## 1. Install

```bash
# Using UV (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
```

## 2. Configure

```bash
cp .env.example .env
# Edit .env and set at minimum:
#   OPENAI_API_KEY="sk-your-key"
#   BIG_MODEL / MIDDLE_MODEL / SMALL_MODEL   (see .env.example for common providers)
```

## 3. Start and use

```bash
# Start the proxy
python start_proxy.py        # or: ./start.sh, uv run claude-code-proxy

# In another terminal, point Claude Code at it
ANTHROPIC_BASE_URL=http://localhost:8082 claude
```

The Claude Code desktop app also works against the proxy: its connectors/plugins
browse UI probes a small set of Anthropic control-plane endpoints, which the
proxy answers with minimal payloads (a fake org from `PROXY_ORG_ID`, a
non-expiring token echo, and empty connector/plugin listings), so the panels
open showing empty lists instead of erroring. See README's "Desktop App
Compatibility" section for details.

## How model mapping works

| Claude Code sends       | Proxy uses       |
|-------------------------|------------------|
| `claude-*opus*`         | `BIG_MODEL`      |
| `claude-*sonnet*`       | `MIDDLE_MODEL`   |
| `claude-*haiku*`        | `SMALL_MODEL`    |
| `claude-proxy-auto` (`AUTO_MODEL_ALIAS`) | `BIG_MODEL` (placeholder: no routing yet) |

Each tier accepts a comma-separated fallback list, and `/effort` levels (`low|medium|high|xhigh|max`, sent as `reasoning_effort` or `output_config.effort`) are translated to your upstream's native reasoning parameters — see the README's "Model Mapping" and "Controlling reasoning effort" sections for full details and provider examples.

## Optional: auto model

The proxy also lists a virtual `claude-proxy-auto` model (4th entry in `/v1/models`, present only when `AUTO_MODEL_ENABLED` is on). It is a placeholder that always resolves to the BIG tier; it does no routing yet (a planned follow-up). Related variables, all optional and all needing a restart: `AUTO_MODEL_ALIAS`, `AUTO_MODEL_ENABLED` and the opt-in request capture `AUTO_SIGNAL_LOG` (plus `AUTO_SIGNAL_LOG_MAX_BYTES` / `AUTO_SIGNAL_LOG_BACKUP_COUNT`). See the README sections "Selecting the auto model in Claude Code" and "Signal log (Phase 0 capture)". Before turning `AUTO_SIGNAL_LOG` on, read its open-proxy warning: with the default `HOST="0.0.0.0"` and no `ANTHROPIC_API_KEY`, any peer that can reach the proxy can append to the log, so bind `HOST` to `127.0.0.1` in `.env`.

## Errors

- An error from the upstream, or the proxy's own 429 when all keys are exhausted, that happens before the first byte of the reply returns a real HTTP status with an Anthropic-style body: `{"type":"error","error":{"type":"...","message":"..."}}`. Two errors keep the `{"detail": ...}` shape: an invalid proxy API key (401) and an invalid request body (422).
- If the upstream fails after streaming has begun, the HTTP status is already 200 because the headers were sent, and the stream ends with one `event: error` block and no `message_stop`. How Claude Code displays this has not been checked in a live session.

## Verify your setup

```bash
# Liveness probe (5-token upstream completion)
curl http://localhost:8082/test-connection

# Offline unit subset, no live server needed (214 tests)
uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py tests/test_model_manager.py tests/test_signal_log.py

# Broader offline run (239 tests)
uv run pytest tests/ --ignore=tests/test_main.py

# Full suite: needs the proxy running on :8082, because tests/test_main.py posts to it
# (if that proxy has AUTO_SIGNAL_LOG on, the test adds lines to its real signal log)
uv run pytest tests/
```

## What you need

- Python 3.9+
- An API key for an OpenAI-compatible provider (OpenAI, Azure OpenAI, Ollama, NVIDIA NIM, ...)
- Claude Code CLI installed
