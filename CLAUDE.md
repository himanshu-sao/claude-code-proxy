# Claude Code Proxy — Project Instructions

A FastAPI proxy translating Anthropic `/v1/messages` requests to OpenAI-compatible
upstreams, so Claude Code can run against any OpenAI-compatible provider.

## Commands

```bash
uv run claude-code-proxy          # run the server (default :8082)
./start.sh / ./stop.sh / ./restart.sh
uv run pytest tests/              # full suite (live-integration tests need the proxy running on :8082)
uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py   # offline unit tests
uv run black src/ && uv run isort src/
```

## Architecture

- `src/api/endpoints.py` — all FastAPI routes (`/v1/messages`, `/v1/models`, `/health`, `/test-connection`)
- `src/conversion/request_converter.py` / `response_converter.py` — Claude ↔ OpenAI schema translation
- `src/conversion/effort_mapper.py` — reasoning-effort translation per model family. Canonical scale is
  `low < medium < high < max`; client `xhigh` maps to `max`. Precedence: client `/effort` > per-tier
  `*_MODEL_EFFORT` env > `REASONING_EFFORT` > built-in `high`. In-session `/effort` must always win.
- `src/core/client.py` — async upstream client: multi-key round-robin, per-key RPM, 429 cooldowns
- `src/core/model_manager.py` — tier mapping (haiku→SMALL, sonnet→MIDDLE, opus→BIG) with comma-separated
  fallback lists and health-check-driven recovery
- `src/core/context_manager.py` — context-window truncation

## Conventions

- Configuration comes exclusively from environment variables / `.env` (never hardcoded); document new
  vars in both `.env.example` and README's "Environment Variables" section.
- `scripts/` holds live-verification scripts that need a running proxy or real API keys — they are not
  part of the pytest suite; keep it that way.

## Docs to keep in sync when behavior changes

README.md (features, env vars, effort mapping table), QUICKSTART.md, `.env.example`.
