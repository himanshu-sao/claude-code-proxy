# Quick Start Guide

## 🚀 Get Started in 3 Steps

### Step 1: Install Dependencies
```bash
# Using UV (recommended)
uv sync

# Or using pip
pip install -r requirements.txt
```

### Step 2: Configure Your Provider

Choose your LLM provider and configure accordingly:

#### OpenAI
```bash
cp .env.example .env
# Edit .env:
# OPENAI_API_KEY="sk-your-openai-key"
# BIG_MODEL="gpt-4o"
# MIDDLE_MODEL="gpt-4o"
# SMALL_MODEL="gpt-4o-mini"
```

#### Azure OpenAI
```bash
cp .env.example .env
# Edit .env:
# OPENAI_API_KEY="your-azure-key"
# OPENAI_BASE_URL="https://your-resource.openai.azure.com/openai/deployments/your-deployment"
# AZURE_API_VERSION="2024-03-01-preview"
# BIG_MODEL="gpt-4"
# MIDDLE_MODEL="gpt-4"
# SMALL_MODEL="gpt-35-turbo"
```

#### Local Models (Ollama)
```bash
cp .env.example .env
# Edit .env:
# OPENAI_API_KEY="dummy-key"
# OPENAI_BASE_URL="http://localhost:11434/v1"
# BIG_MODEL="llama3.1:70b"
# MIDDLE_MODEL="llama3.1:70b"
# SMALL_MODEL="llama3.1:8b"
```

### Step 3: Start and Use

```bash
# Start the proxy server
python start_proxy.py

# In another terminal, use with Claude Code
ANTHROPIC_BASE_URL=http://localhost:8082 claude
```

## 🎯 How It Works

| Your input | Proxy action | Result |
|-----------|--------------|--------|
| Claude Code sends `claude-*sonnet*` | Maps to your `MIDDLE_MODEL` | Uses the middle-tier model |
| Claude Code sends `claude-*opus*` | Maps to your `BIG_MODEL` | Uses the big-tier model |
| Claude Code sends `claude-*haiku*` | Maps to your `SMALL_MODEL` | Uses the small-tier model |

Each tier variable accepts a comma-separated fallback list (`BIG_MODEL="a,fallback1,fallback2"`) — on repeated failures the proxy moves down the list and probes the primary in the background to restore it when healthy.

## 🧠 Controlling reasoning effort

Claude Code 2.1.x's `/effort low|medium|high|xhigh` is honored per request; it always wins over proxy env defaults.

- Proxy-side defaults (used only when the client sends no effort):
  - `REASONING_EFFORT` — global fallback (built-in default: `high`).
  - `BIG_MODEL_EFFORT` / `MIDDLE_MODEL_EFFORT` / `SMALL_MODEL_EFFORT` — per-tier overrides of the global default.
- The proxy translates each level to the upstream's native vocabulary (string, numeric, or chat-template-kwargs) — see README's "Controlling reasoning effort" for the full mapping table.

## 📋 What You Need

- Python 3.9+
- API key for your chosen provider
- Claude Code CLI installed
- 2 minutes to configure

## 🔧 Default Settings

- Server runs on `http://localhost:8082`
- Maps haiku → `SMALL_MODEL`, sonnet → `MIDDLE_MODEL`, opus → `BIG_MODEL`
- Supports streaming, function calling, images, `/effort` reasoning control

## 🧪 Test Your Setup

```bash
# Unit tests (no live server needed)
uv run pytest tests/test_effort_mapper.py tests/test_endpoints.py tests/test_context_manager.py

# Validate the reasoning-effort envelope against NVIDIA NIM (needs a real NIM key)
NVIDIA_API_KEY=nvapi-... uv run scripts/test_nim_effort.py
```

That's it! Now Claude Code can use any OpenAI-compatible provider! 🎉