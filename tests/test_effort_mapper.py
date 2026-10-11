"""Unit tests for the reasoning-effort routing layer.

These cover the canonical normalization (including Claude Code's xhigh -> max)
and the per-provider envelope/vocabulary mapping for every model family the
proxy targets: NIM GLM-5.x, gpt-oss / o-series, kimi-k3 / deepseek-r1,
deepseek-v4.1-flash (numeric), and NVIDIA Nemotron (chat_template_kwargs).
"""
from src.conversion.effort_mapper import (
    CANONICAL_EFFORTS,
    DEFAULT_EFFORT,
    EffortSpec,
    normalize_effort,
    provider_effort,
    resolve_effort,
)


# --- normalize_effort: precedence and canonicalization ---

def test_normalize_prefers_client_value_over_env_default():
    # The env var is a default only: in-session /effort always wins.
    assert normalize_effort("low", "high") == "low"
    assert normalize_effort("max", "low") == "max"


def test_normalize_uses_env_default_when_client_silent():
    assert normalize_effort(None, "low") == "low"
    assert normalize_effort("", "medium") == "medium"


def test_normalize_uses_claude_value_when_no_override():
    assert normalize_effort("low", None) == "low"
    assert normalize_effort("medium", None) == "medium"
    assert normalize_effort("high", None) == "high"


def test_normalize_defaults_when_missing():
    assert normalize_effort(None, None) == DEFAULT_EFFORT
    assert normalize_effort("", None) == DEFAULT_EFFORT


def test_normalize_maps_xhigh_to_max():
    # Claude Code's top level becomes the canonical max.
    assert normalize_effort("xhigh", None) == "max"
    assert normalize_effort(None, "xhigh") == "max"


def test_normalize_is_case_insensitive_and_trims():
    assert normalize_effort("  HIGH ", None) == "high"


def test_normalize_unknown_falls_back_to_default():
    assert normalize_effort("bogus", None) == DEFAULT_EFFORT
    assert normalize_effort(None, "not-a-level") == DEFAULT_EFFORT


def test_canonical_scale_order():
    assert CANONICAL_EFFORTS == ("low", "medium", "high", "max")


# --- resolve_effort: provider envelopes ---

def test_glm5_vocabulary():
    # GLM-5.x speaks low|high|max (no "medium"); medium nudges up to high.
    assert resolve_effort("z-ai/glm-5.3", "low").reasoning_effort == "low"
    assert resolve_effort("z-ai/glm-5.3", "medium").reasoning_effort == "high"
    assert resolve_effort("z-ai/glm-5.3", "high").reasoning_effort == "high"
    assert resolve_effort("z-ai/glm-5.3", "max").reasoning_effort == "max"
    assert resolve_effort("z-ai/glm-5.3", "max").chat_template_kwargs is None


def test_gpt_oss_vocabulary():
    # gpt-oss speaks low|medium|high (no "max"); max caps down to high.
    assert resolve_effort("openai/gpt-oss-120b", "low").reasoning_effort == "low"
    assert resolve_effort("openai/gpt-oss-20b", "medium").reasoning_effort == "medium"
    assert resolve_effort("openai/gpt-oss-120b", "high").reasoning_effort == "high"
    assert resolve_effort("openai/gpt-oss-120b", "max").reasoning_effort == "high"


def test_deepseek_v4_numeric():
    # deepseek-v4.1-flash takes a numeric reasoning_effort 1-100.
    assert resolve_effort("deepseek-ai/deepseek-v4.1-flash", "low").reasoning_effort == 20
    assert resolve_effort("deepseek-ai/deepseek-v4.1-flash", "medium").reasoning_effort == 50
    assert resolve_effort("deepseek-ai/deepseek-v4.1-flash", "high").reasoning_effort == 80
    assert resolve_effort("deepseek-ai/deepseek-v4.1-flash", "max").reasoning_effort == 100


def test_nemotron_template_kwargs():
    # Nemotron ultra: thinking on/off + medium_effort; no reasoning_effort.
    low = resolve_effort("nvidia/nemotron-3-ultra-550b-a55b", "low")
    assert low.reasoning_effort is None
    assert low.chat_template_kwargs == {"enable_thinking": False}

    med = resolve_effort("nvidia/nemotron-3-ultra-550b-a55b", "medium")
    assert med.chat_template_kwargs == {"enable_thinking": True, "medium_effort": True}

    high = resolve_effort("nvidia/nemotron-3-ultra-550b-a55b", "high")
    assert high.chat_template_kwargs == {"enable_thinking": True, "medium_effort": True}

    max_ = resolve_effort("nvidia/nemotron-3-ultra-550b-a55b", "max")
    assert max_.chat_template_kwargs == {"enable_thinking": True}
    assert "medium_effort" not in max_.chat_template_kwargs


def test_nemotron_non_ultra_no_medium_effort():
    # Non-ultra Nemotron gets plain on/off, never medium_effort.
    spec = resolve_effort("nvidia/nemotron-3.5-lightning-30b-a3b", "medium")
    assert spec.chat_template_kwargs == {"enable_thinking": True}


def test_always_on_thinking_models_omit_effort():
    assert resolve_effort("moonshotai/kimi-k2-thinking", "high").has_effect is False
    assert resolve_effort("qwen/qwen3-next-80b-a3b-thinking", "low").has_effect is False


def test_generic_reasoning_models_cap_max():
    # deepseek-r1 / kimi-k3 / o-series follow the OpenAI vocabulary.
    assert resolve_effort("deepseek-ai/deepseek-r1", "max").reasoning_effort == "high"
    assert resolve_effort("moonshotai/kimi-k3", "low").reasoning_effort == "low"
    assert resolve_effort("o1-mini", "medium").reasoning_effort == "medium"


def test_provider_effort_backwards_compat():
    assert provider_effort("z-ai/glm-5.3", "max") == "max"
    assert provider_effort("nvidia/nemotron-3-ultra-550b-a55b", "high") is None
    assert provider_effort("moonshotai/kimi-k2-thinking", "high") is None
