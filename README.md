# Claude Code Proxy

A proxy server that enables **Claude Code** to work with OpenAI-compatible API providers. Convert Claude API requests to OpenAI API calls, allowing you to use various LLM providers through the Claude Code CLI.

![Claude Code Proxy](demo.png)

## Features

- **Full Claude API Compatibility**: Complete `/v1/messages` endpoint support
- **Multiple Provider Support**: OpenAI, Azure OpenAI, local models (Ollama), and any OpenAI-compatible API
- **Smart Model Mapping**: Configure BIG / MIDDLE / SMALL models via environment variables, with per-tier fallback lists and automatic health-driven failover
- **Reasoning Effort Control**: Honors Claude Code's `/effort` levels (low/medium/high/xhigh/max), read from either the top-level `reasoning_effort` or `output_config.effort`, and maps them to each upstream's native API (top-level string or chat-template-kwargs depending on the model)
- **Virtual Auto Model (placeholder)**: an extra `claude-proxy-auto` alias (4th entry in `/v1/models`, configurable or disableable) that currently just resolves to the BIG tier; it does no routing yet
- **Opt-in Signal Log**: `AUTO_SIGNAL_LOG=1` records one line per accepted `/v1/messages` request in `logs/auto_signal.log` (no raw message text or header values, but it does hold two unsalted 8-hex hashes and any identifier-shaped names the client sends), with an analyzer script, to study real Claude Code traffic (off by default; if the proxy is reachable by others and `ANTHROPIC_API_KEY` is unset, any peer can append to it: see the open-proxy warning in "Signal log (Phase 0 capture)")
- **Function Calling**: Complete tool use support with proper conversion
- **Streaming Responses**: Real-time SSE streaming support
- **Image Support**: Base64 encoded image input
- **Custom Headers**: Automatic injection of custom HTTP headers for API requests
- **Desktop App Compatibility**: Minimal Anthropic control-plane endpoints (`/api/organizations`, `/v1/me`, a non-expiring `/v1/oauth/token` echo, empty connector/plugin listings) so the Claude Code desktop app's connectors/plugins browse UI opens instead of erroring; any other unknown `/v1` or `/api` path returns a well-formed Anthropic-style 404
- **Error Handling**: Comprehensive error handling and logging

## Quick Start

### 1. Install Dependencies

```bash
# Using UV (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and add your API configuration
# Note: Environment variables are automatically loaded from .env file
```

### 3. Start Server

```bash
# Direct run
python start_proxy.py

# Or with UV
uv run claude-code-proxy

# Or with docker compose
docker compose up -d
```

### 4. Use with Claude Code

```bash
# If ANTHROPIC_API_KEY is not set in the proxy:
ANTHROPIC_BASE_URL=http://localhost:8082 ANTHROPIC_API_KEY="any-value" claude

# If ANTHROPIC_API_KEY is set in the proxy:
ANTHROPIC_BASE_URL=http://localhost:8082 ANTHROPIC_API_KEY="exact-matching-key" claude
```

## Configuration

The application automatically loads environment variables from a `.env` file in the project root using `python-dotenv`. You can also set environment variables directly in your shell. `.env` is loaded once at import with `load_dotenv(override=True)`, so a key present in `.env` **overrides** a shell export of the same name, and any change needs a proxy restart.

### Environment Variables

**Required:**

- `OPENAI_API_KEY` - Your API key for the target provider

**Security:**

- `ANTHROPIC_API_KEY` - Expected Anthropic API key for client validation
  - If set, clients must provide this exact API key to access the proxy
  - If not set, any API key will be accepted

**Desktop App Compatibility:**

- `PROXY_ORG_ID` - Fake organization id returned by the desktop-compat endpoints (`GET /api/organizations`, `GET /v1/organizations`, `GET /v1/me`, and the `PROXY_ORG_ID`-echoed sub-resource listings) (default: `claude-code-proxy-org`)

**Model Configuration:**

Models are mapped by tier. Each tier accepts a comma-separated list — the first entry is the primary, the rest are automatic fallbacks with health-check-driven recovery:

- `BIG_MODEL` - Model(s) for Claude opus requests (default: `gpt-4o`)
- `MIDDLE_MODEL` - Model(s) for Claude sonnet requests (default: value of `BIG_MODEL`)
- `SMALL_MODEL` - Model(s) for Claude haiku requests (default: `gpt-4o-mini`)

**Reasoning Effort:**

Claude Code's `/effort` levels (`low`, `medium`, `high`, `xhigh`, `max`) flow through to the upstream, carried in either the top-level `reasoning_effort` field or `output_config.effort`. The proxy normalizes them (`xhigh` and `max` both map to the canonical `max`) and translates to each model's native vocabulary — e.g. GLM-5.x gets `low/high/max`, gpt-oss gets `low/medium/high`, deepseek-v4.x gets `low/high` (`medium` and `max` become `high`), and Nemotron models get `chat_template_kwargs` thinking switches. Full precedence: top-level `reasoning_effort` > `output_config.effort` > per-tier `*_MODEL_EFFORT` > `REASONING_EFFORT` > built-in `high`. The env values below are defaults, applied only when the client sends no effort:

- `BIG_MODEL_EFFORT`, `MIDDLE_MODEL_EFFORT`, `SMALL_MODEL_EFFORT` - Per-tier default effort (`low|medium|high|max|xhigh`). An in-session `/effort` always overrides these.
- `REASONING_EFFORT` - Global default effort for all tiers when a per-tier value is not set (built-in fallback: `high`).

**Auto Model** (placeholder, no routing yet; restart to change):

- `AUTO_MODEL_ALIAS` - Id of the virtual auto model (default: `claude-proxy-auto`). Matched after stripping whitespace and ignoring case; an empty value means the default. `/v1/models` lists it with the casing you set.
- `AUTO_MODEL_ENABLED` - Default `true`. Only `false`, `0`, `no`, `off` or a **blank** value (case-insensitive, after stripping) disable it; **any other value, including a typo such as `flase`, leaves it enabled** (fails open). When disabled the `/v1/models` entry is removed and the alias is treated like any other unknown name (see Model Mapping).

**Auto Model Signal Log** (off by default; restart to change; see "Signal log (Phase 0 capture)"):

- `AUTO_SIGNAL_LOG` - Default off. Only `1`, `true`, `yes` or `on` (case-insensitive) enable it; **anything else is off** (fails closed, the opposite of `AUTO_MODEL_ENABLED`). Read the open-proxy warning in "Signal log (Phase 0 capture)" before enabling it.
- `AUTO_SIGNAL_LOG_MAX_BYTES` - Size at which `logs/auto_signal.log` rotates (default: `5242880`, clamped to at most `1073741824`, 1 GiB). Invalid, empty or non-positive values use the default.
- `AUTO_SIGNAL_LOG_BACKUP_COUNT` - Rotated files kept (default: `3`, clamped to at most `20`). Invalid, empty or non-positive values use the default.

**Rate Limiting and Reliability:**

- `RPM_LIMIT` - Max requests per minute per API key (default: `40`)
- `MODEL_FAILURE_THRESHOLD` - Consecutive failures before switching to a fallback model (default: `3`)
- `MODEL_HEALTH_CHECK_INTERVAL` - Seconds between background probes of the primary model (default: `60`)

**API Configuration:**

- `OPENAI_BASE_URL` - API base URL (default: `https://api.openai.com/v1`)
- `AZURE_API_VERSION` - Azure OpenAI API version (e.g. `2024-03-01-preview`); see the Azure provider example below

**Server Settings:**

- `HOST` - Server host (default: `0.0.0.0`)
- `PORT` - Server port (default: `8082`)
- `LOG_LEVEL` - Logging level (default: `INFO`)

**Performance:**

- `MAX_TOKENS_LIMIT` - Max response tokens (default: `4096`)
- `MIN_TOKENS_LIMIT` - Min response tokens (default: `100`); raise this (e.g. `4096`) for reasoning models whose thinking consumes output budget
- `REQUEST_TIMEOUT` - Request timeout in seconds (default: `90`)
- `MAX_RETRIES` - Extra upstream attempts after a failure (default: `2`, i.e. up to 3 calls). Applies to connection errors/timeouts, 408, 409, 429 and 5xx responses, via the OpenAI SDK; `0` disables retries; negative values are treated as `0`. Each attempt can take up to `REQUEST_TIMEOUT`
- `STREAM_MAX_RETRIES` - Same as `MAX_RETRIES`, but only for streamed (`stream: true`) upstream calls (default: `0`). Keeping it at `0` lets Claude Code's own retry loop handle transient failures before the first byte. Non-integer or negative values fall back to `0` with a warning. `MAX_RETRIES` still applies to non-stream calls.

**Multi-Key / Multi-Provider:**

- `OPENAI_API_KEY` accepts a comma-separated list of keys (`"key1,key2,..."`) — requests are round-robined across them with per-key RPM accounting and 60 s cooldown penalties on 429s. All keys share `OPENAI_BASE_URL`.

**Custom Headers:**

- `CUSTOM_HEADER_*` - Custom headers for API requests (e.g., `CUSTOM_HEADER_ACCEPT`, `CUSTOM_HEADER_AUTHORIZATION`)
  - Uncomment in `.env` file to enable custom headers

### Custom Headers Configuration

Add custom headers to your API requests by setting environment variables with the `CUSTOM_HEADER_` prefix:

```bash
# Uncomment to enable custom headers
# CUSTOM_HEADER_ACCEPT="application/jsonstream"
# CUSTOM_HEADER_CONTENT_TYPE="application/json"
# CUSTOM_HEADER_USER_AGENT="your-app/1.0.0"
# CUSTOM_HEADER_AUTHORIZATION="Bearer your-token"
# CUSTOM_HEADER_X_API_KEY="your-api-key"
# CUSTOM_HEADER_X_CLIENT_ID="your-client-id"
# CUSTOM_HEADER_X_CLIENT_VERSION="1.0.0"
# CUSTOM_HEADER_X_REQUEST_ID="unique-request-id"
# CUSTOM_HEADER_X_TRACE_ID="trace-123"
# CUSTOM_HEADER_X_SESSION_ID="session-456"
```

### Header Conversion Rules

Environment variables with the `CUSTOM_HEADER_` prefix are automatically converted to HTTP headers:

- Environment variable: `CUSTOM_HEADER_ACCEPT`
- HTTP Header: `ACCEPT`

- Environment variable: `CUSTOM_HEADER_X_API_KEY`
- HTTP Header: `X-API-KEY`

- Environment variable: `CUSTOM_HEADER_AUTHORIZATION`
- HTTP Header: `AUTHORIZATION`

### Supported Header Types

- **Content Type**: `ACCEPT`, `CONTENT-TYPE`
- **Authentication**: `AUTHORIZATION`, `X-API-KEY`
- **Client Identification**: `USER-AGENT`, `X-CLIENT-ID`, `X-CLIENT-VERSION`
- **Tracking**: `X-REQUEST-ID`, `X-TRACE-ID`, `X-SESSION-ID`

### Usage Example

```bash
# Basic configuration
OPENAI_API_KEY="sk-your-openai-api-key-here"
OPENAI_BASE_URL="https://api.openai.com/v1"

# Enable custom headers (uncomment as needed)
CUSTOM_HEADER_ACCEPT="application/jsonstream"
CUSTOM_HEADER_CONTENT_TYPE="application/json"
CUSTOM_HEADER_USER_AGENT="my-app/1.0.0"
CUSTOM_HEADER_AUTHORIZATION="Bearer my-token"
```

The proxy will automatically include these headers in all API requests to the target LLM provider.

### Model Mapping

The proxy maps Claude model requests to your configured models by tier:

| Claude Request    | Mapped To      | Default                      |
| ----------------- | -------------- | ---------------------------- |
| haiku models      | `SMALL_MODEL`  | `gpt-4o-mini`                |
| sonnet models     | `MIDDLE_MODEL` | value of `BIG_MODEL`         |
| opus models       | `BIG_MODEL`    | `gpt-4o`                     |
| `AUTO_MODEL_ALIAS` (`claude-proxy-auto`) | active `BIG_MODEL` (follows a BIG fallback); `reason=auto-placeholder` on the request log line | checked first, before every other row (including the haiku/sonnet/opus substring rules) |
| `gpt-*` / `o1-*` / `ep-*` / `doubao-*` / `deepseek-*` | used as-is (tier `unknown`) | — |

Each tier variable accepts a comma-separated fallback list (e.g. `BIG_MODEL="a,a2,a3"`); on repeated failures the proxy moves down the list and probes the primary in the background to restore it when healthy. Reasoning effort defaults are independently tunable per tier via `BIG_MODEL_EFFORT` / `MIDDLE_MODEL_EFFORT` / `SMALL_MODEL_EFFORT`.

The auto alias does **no routing**: it always resolves to the BIG tier, and routing is not implemented yet (a planned follow-up). If `AUTO_MODEL_ENABLED` is off, the alias is treated like any other unknown name: the pass-through prefixes `gpt-`, `o1-`, `ep-`, `doubao-` and `deepseek-` (case-sensitive) are checked first and the name is used as-is with tier `unknown` (so `gpt-auto` is passed through); otherwise a name containing `haiku`, `sonnet` or `opus` (case-insensitive) maps to that tier (so `my-opus-auto` goes to BIG); everything else, including the default `claude-proxy-auto` and names such as `my-auto` or `GPT-auto`, goes to BIG with `reason=tier-map`.

### Context windows

Context and output limits are resolved in this order: `MODEL_CONTEXT_LIMITS` env > discovered/cached limits (`model_contexts_cache.json`) > built-in table > `(32000, 4096)`. Two NVIDIA models are curated in `model_contexts_cache.json`: `mistralai/mistral-large-4-1t-a52b` and `minimaxai/minimax-m3.1-flash`, both `[262144, 32768]`.

- **262,144 is NVIDIA's published hosted spec. It is NOT verified live**; the vendors claim about 1M, so the hosted limit may be lower than the model's native one.
- **32,768 is this repo's own default output cap and has no source** (same precedent as commit `c5a0b70`).
- The file is read from the **current directory** at startup only; restart after editing it. If none exists there, the proxy creates one in that directory shortly after startup, once the background discovery task has run (unless `MODEL_CONTEXT_LIMITS` already covers every configured model).
- When a configured `BIG_MODEL`/`MIDDLE_MODEL`/`SMALL_MODEL` is missing from it, the proxy runs upstream discovery and **rewrites this tracked file**; discovery output can overwrite curated entries, so review `git diff` after a first run with a new model.

### Provider Examples

#### OpenAI

```bash
OPENAI_API_KEY="sk-your-openai-key"
OPENAI_BASE_URL="https://api.openai.com/v1"
BIG_MODEL="gpt-4o"
MIDDLE_MODEL="gpt-4o"
SMALL_MODEL="gpt-4o-mini"
```

#### Azure OpenAI

```bash
OPENAI_API_KEY="your-azure-key"
OPENAI_BASE_URL="https://your-resource.openai.azure.com/openai/deployments/your-deployment"
BIG_MODEL="gpt-4"
MIDDLE_MODEL="gpt-4"
SMALL_MODEL="gpt-35-turbo"
```

#### Local Models (Ollama)

```bash
OPENAI_API_KEY="dummy-key"  # Required but can be dummy
OPENAI_BASE_URL="http://localhost:11434/v1"
BIG_MODEL="llama3.1:70b"
MIDDLE_MODEL="llama3.1:70b"
SMALL_MODEL="llama3.1:8b"
```

#### Other Providers

Any OpenAI-compatible API can be used by setting the appropriate `OPENAI_BASE_URL`.

## Usage Examples

### Basic Chat

```python
import httpx

response = httpx.post(
    "http://localhost:8082/v1/messages",
    json={
        "model": "claude-3-5-sonnet-20241022",  # Maps to MIDDLE_MODEL
        "max_tokens": 100,
        "messages": [
            {"role": "user", "content": "Hello!"}
        ]
    }
)
```

## Integration with Claude Code

This proxy is designed to work seamlessly with Claude Code CLI:

```bash
# Start the proxy
./start.sh

# Use Claude Code with the proxy
ANTHROPIC_BASE_URL=http://localhost:8082 claude

# Or set permanently
export ANTHROPIC_BASE_URL=http://localhost:8082
claude
```

### Controlling reasoning effort in Claude Code

In Claude Code 2.1.x, use `/effort low|medium|high|xhigh|max` to change it on the fly, or set a starting level with `CLAUDE_CODE_EFFORT_LEVEL`. The proxy routes each level to the correct parameter for your configured upstream model:

| `/effort` | GLM-5.x (`z-ai/glm-5.3`) | gpt-oss (`openai/gpt-oss-*`) | deepseek-v4.1-flash | Nemotron (`nvidia/nemotron-*`) | kimi-k2-thinking / qwen3-*-thinking |
|---|---|---|---|---|---|
| `low` | `low` | `low` | `low` | thinking **off** | *(omitted)* |
| `medium` | `high` | `medium` | `high` | thinking on (`medium_effort` for `ultra` only) | *(omitted)* |
| `high` | `high` | `high` | `high` | thinking on (`medium_effort` for `ultra` only) | *(omitted)* |
| `xhigh` / `max` | **`max`** | `high` (cap) | `high` (cap) | thinking on (no `medium_effort`) | *(omitted)* |

NVIDIA NIM's deepseek-v4.1-flash changed its effort contract on 2026-10-11: it previously took a numeric 1–100 value, then started rejecting integers ("expected string or map") and also rejects `"medium"` in-stream. The table reflects the live-verified string vocabulary.

Notes:

- In-session `/effort` always wins over the proxy env vars.
- A `max` level maps to the same canonical value as `xhigh`, so its upstream translation is identical to the `xhigh` row. A top-level `reasoning_effort: "max"` is accepted.
- The client level can arrive as top-level `reasoning_effort` or as `output_config.effort`. Precedence: top-level `reasoning_effort` > `output_config.effort` > per-tier `*_MODEL_EFFORT` > `REASONING_EFFORT` > built-in `high`.
- The top-level field is an exact, case-sensitive set (`low|medium|high|xhigh|max`): `bogus` or `HIGH` returns 422. `output_config.effort` is stripped and lower-cased, and a malformed `output_config` (not an object, `effort` not a string, unknown level) is ignored, never rejected, so the env defaults apply.
- Nemotron models get `chat_template_kwargs` thinking switches; `medium_effort` is only added when the model name contains `ultra`.
- The env defaults are independent per tier — a common pattern is `SMALL_MODEL_EFFORT=low` (cheap haiku with thinking off) while leaving `BIG_MODEL` at the built-in `high`.
- `kimi-k2-thinking` / `qwen3-*-thinking` are always-on reasoning models: the proxy sends no reasoning parameter to them (their chat template forces a thinking trace).

### Selecting the auto model in Claude Code

`claude-proxy-auto` is a placeholder: it always resolves to the BIG tier and does no routing yet (a planned follow-up; see Model Mapping). To pick it in Claude Code:

```bash
export ANTHROPIC_BASE_URL=http://localhost:8082
export ANTHROPIC_CUSTOM_MODEL_OPTION=claude-proxy-auto
export ANTHROPIC_CUSTOM_MODEL_OPTION_NAME="Auto"                       # optional label
export ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION="Proxy auto alias (BIG tier for now)"  # optional
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1   # fill the /model picker from /v1/models
```

- `ANTHROPIC_CUSTOM_MODEL_OPTION` adds the id to the `/model` picker; `_NAME` and `_DESCRIPTION` set its label. `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` makes Claude Code list the models returned by `GET /v1/models` (the alias is the 4th entry, display name `Auto (routes to big tier)`; that is the literal text the endpoint returns, and today it only means BIG).
- Claude Code assumes a 200K context window for an id it does not recognise. Set `CLAUDE_CODE_MAX_CONTEXT_TOKENS` to the real window or use `/autocompact` so it compacts in time.
- Optional: `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1` makes Claude Code send extra hint headers such as `x-claude-code-request-class`, which the signal log records as `req_class`.
- `ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES=effort,thinking,xhigh_effort,max_effort` is **unverified** behind a gateway; do not rely on it to enable effort or thinking.

These settings come from Claude Code's documentation and have **not** been checked against a real Claude Code run.

### Signal log (Phase 0 capture)

**Open-proxy warning.** `HOST` defaults to `0.0.0.0`, and client key validation is off when `ANTHROPIC_API_KEY` is unset, so by default any peer that can reach the proxy can append records to this log. This capture is meant for a local, single-operator run. The strongest fix is to bind `HOST` to a loopback address (`HOST="127.0.0.1"`) **in `.env`**: `.env` is loaded with `override=True` and `.env.example` ships `HOST="0.0.0.0"`, so `HOST=127.0.0.1 ./start.sh` on the command line does not take effect while `.env` sets `HOST`. If you set `ANTHROPIC_API_KEY` instead, use a private random value: the `.env.example` value `your-expected-anthropic-api-key` is public, so copying it verbatim turns validation on but lets anyone who has read this repo in. A configured key protects `POST /v1/messages`, `POST /v1/messages/count_tokens` and the desktop-compat routes (`/v1/me`, `/api/organizations`, `/v1/organizations`, `/v1/oauth/token`, `/v1/mcp_servers`, `/api/connectors`, `/api/plugins`); it does not protect `/health`, `/test-connection`, `/v1/models` or `/`.

A temporary, opt-in capture to learn what real Claude Code requests look like before any routing is built. Off by default; set `AUTO_SIGNAL_LOG=1` and restart.

- **What is logged:** every request accepted by `POST /v1/messages`, for all models (not only the alias), streaming or not, appends one line to `logs/auto_signal.log`. It is written after authentication and validation, so a 401 or 422 is never logged; an accepted request is logged once even if the upstream later fails or the client disconnects. A failed write never changes the response (it is visible only at `DEBUG`).
- **Files:** append-only, survives restarts, rotates at `AUTO_SIGNAL_LOG_MAX_BYTES` keeping `AUTO_SIGNAL_LOG_BACKUP_COUNT` files (`auto_signal.log.1` ... `.N`). It is separate from `logs/proxy.log` (truncated on each start), and `logs/` is gitignored. Rotation is safe for the default single uvicorn process only; multiple workers are unsupported.
- **Configuration:** the on/off switch is read on every request, but `.env` is only loaded at startup (and overrides a shell export), so restart after changing it. `AUTO_SIGNAL_LOG_MAX_BYTES` and `AUTO_SIGNAL_LOG_BACKUP_COUNT` are read once, when the first record is written (the handler is created then).
- **Privacy:** no message, system, tool or header **values**, and no base64. Each line holds identifier-shaped names (body fields, header names, `output_config` and `metadata` keys, the model name; anything not matching `[A-Za-z0-9_.:/-]{1,64}` is logged as `other`), counts, booleans, enum values, and two 8-hex **unsalted** hashes: `sid_hash` (the `x-claude-code-session-id` header) and `fm_hash` (the first user message: `<system-reminder>` blocks removed, then whitespace normalised, then cut to the first 512 characters; `fm_stripped` says whether any were removed). Names that match the pattern are logged verbatim, so a key-like string used as a model name, header name or key (for example one starting `sk-` or `ghp_`) would be kept. The hashes are only 32 bits and unsalted, so a short or templated prompt can be confirmed by someone who hashes a guess and can read the file. Keep the file local.
- **Retention and disk use:** to finish a capture, set `AUTO_SIGNAL_LOG` off and restart the proxy **first** (the proxy keeps the file open, so deleting it while it runs leaves the proxy writing to an unlinked file), then delete `logs/auto_signal.log*`, rotated files included. Worst-case disk use is (`AUTO_SIGNAL_LOG_BACKUP_COUNT` + 1) x `AUTO_SIGNAL_LOG_MAX_BYTES`: up to 21 files x 1 GiB, about 21 GiB, at the maximum clamps, and a peer can drive it when the proxy is open. Keep the defaults (about 20 MB).
- **File mode:** the file is opened with mode `0600` and `O_NOFOLLOW` where the platform has it. Where `fchmod` exists the file mode is forced to exactly `0600` regardless of umask; without it the umask can only make it stricter. An existing `logs/` directory keeps its mode: the proxy already creates `logs/` with default modes at startup, so do not assume the directory is `0700`. If the module itself had to create the directory under a very strict umask (for example `0277`), it could come out non-writable and writes would be silently skipped (failures are visible only at `DEBUG`).
- **Cost:** the write runs inline on the event loop: about 0.12 ms for a 41 KB body, 6-10 ms for a 2 MB body, 1.3-1.8 ms at a file rollover. Measured in-process only, not under concurrent load.

Analyze a capture (include the rotated files):

```bash
python3 scripts/analyze_signal_log.py logs/auto_signal.log*
```

The shell expands the glob (the script does not), so run it after the log exists: zsh stops with "no matches found" otherwise, while bash passes the pattern through and the script warns about a missing file and exits 0. The script uses only the standard library, skips lines it cannot parse, and exits 2 only when no file is given. Its verdict on whether `fm_hash` could serve as a conversation key: **usable** only if main-thread constancy (one distinct `fm_hash` per session) is at least 95% **and** the share of sessions whose `fm_hash` is shared with another session is at most 5%, with at least 10 sessions overall and at least 10 sessions with 2+ main-thread turns. Below those sample sizes it prints "insufficient sample" (or "undetermined" when no record carries both hashes, or "NOT shown to be usable" when the thresholds are missed). The 95% and 5% thresholds are the author's own choice and have not been validated.

**What is NOT verified.** No live HTTP run of this feature has been done (local port binding was declined; checks were in-process only). Also unverified: the real Claude Code request shape (`output_config.effort`, the headers, adaptive thinking) and `_SUPPORTED_CAPABILITIES` behaviour; the 262,144 and 32,768 context figures; latency under load, shutdown and real client disconnects; the default log-path modes in a running proxy; Windows or platforms without `O_NOFOLLOW`; multi-worker use; the 95%/5% thresholds; and the full live `pytest tests/` suite.

### Endpoints reference

| Path                                | Purpose                                  |
| ----------------------------------- | ---------------------------------------- |
| `POST /v1/messages`                 | Main messages endpoint (Claude schema)   |
| `POST /v1/messages/count_tokens`    | Token-count endpoint (Anthropic format)  |
| `GET  /v1/models`                   | Models list (three tier aliases plus the optional auto alias) |
| `GET  /health`                      | Health + per-key RPM usage/penalties     |
| `GET  /test-connection`             | Liveness: probes upstream with a 5-token completion |
| `GET/HEAD /api/hello` and `/hello`  | Tiny probe for Claude extensions         |
| `GET  /`                            | Version + effective config summary       |

## Testing

```bash
# Offline unit subset, no server needed (214 tests)
uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py tests/test_model_manager.py tests/test_signal_log.py

# Broader offline run (239 tests; also covers tests/test_compat_endpoints.py)
uv run pytest tests/ --ignore=tests/test_main.py

# Full suite: additionally needs a live proxy on :8082, because tests/test_main.py posts to it
uv run pytest tests/

# Validate the reasoning-effort envelope against a live NVIDIA NIM endpoint
NVIDIA_API_KEY=nvapi-... uv run scripts/test_nim_effort.py [model]
```

Notes: `tests/test_main.py` posts to a **live** proxy on `localhost:8082`; if that proxy has `AUTO_SIGNAL_LOG` on, the test adds lines to its real signal log. The offline tests assume no `AUTO_*` keys in your environment. Inside a git worktree, run `python -m pytest ...` with the worktree as the current directory so tests import that worktree's `src` and not another checkout's. The test counts above (214 / 239) are the current numbers and will change as tests are added.

## Development

### Using UV

```bash
# Install dependencies
uv sync

# Run server
uv run claude-code-proxy

# Format code
uv run black src/
uv run isort src/

# Type checking
uv run mypy src/
```

### Project Structure

```
claude-code-proxy/
├── src/
│   ├── main.py                  # Server entrypoint
│   ├── api/endpoints.py         # FastAPI routes (/v1/messages, /v1/models, /health, ...)
│   ├── conversion/
│   │   ├── request_converter.py   # Claude request -> OpenAI request
│   │   ├── response_converter.py  # OpenAI response -> Claude response
│   │   └── effort_mapper.py       # Reasoning-effort translation per model family
│   ├── core/
│   │   ├── client.py              # Async upstream client with multi-key RPM + retries
│   │   ├── config.py              # Env-var configuration
│   │   ├── model_manager.py       # Tier mapping + fallback/health failover
│   │   ├── context_manager.py     # Context-window truncation
│   │   ├── signal_log.py          # Opt-in request signal log (no raw message text; AUTO_SIGNAL_LOG)
│   │   └── provider_discovery.py  # Upstream provider detection
│   └── models/                    # Pydantic schemas (Claude + OpenAI)
├── tests/                       # Unit tests (pytest)
├── scripts/                     # Live/verification scripts (need running proxy or real keys)
│   └── analyze_signal_log.py    #   offline analyzer for logs/auto_signal.log (no proxy needed)
├── start_proxy.py               # Startup script
├── .env.example                 # Config template
└── README.md                    # This file
```

## Performance

- **Async/await** for high concurrency
- **Connection pooling** for efficiency
- **Streaming support** for real-time responses
- **Configurable timeouts** and retries
- **Smart error handling** with detailed logging

## License

MIT License
