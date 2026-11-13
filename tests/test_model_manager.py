import pytest

from src.core.config import DEFAULT_AUTO_MODEL_ALIAS, parse_auto_enabled
from src.core.model_manager import ModelManager


class FakeConfig:
    """Minimal stand-in for Config exposing what ModelManager reads."""

    def __init__(self, alias="claude-proxy-auto", enabled=True):
        self.auto_model_alias = alias
        self.auto_model_enabled = enabled
        self.big_models = ["big-primary", "big-fallback"]
        self.middle_models = ["mid-primary"]
        self.small_models = ["small-primary"]
        self._active_big_idx = 0

    def get_active_model(self, tier):
        if tier == "big":
            return self.big_models[self._active_big_idx]
        if tier == "middle":
            return self.middle_models[0]
        return self.small_models[0]


@pytest.fixture
def cfg():
    return FakeConfig()


@pytest.fixture
def mm(cfg):
    return ModelManager(cfg)


@pytest.mark.parametrize(
    "name", ["claude-proxy-auto", "Claude-Proxy-Auto", "  CLAUDE-PROXY-AUTO  "]
)
def test_default_alias_case_and_whitespace(mm, name):
    assert mm.is_auto_alias(name) is True
    assert mm.map_claude_model_to_openai(name) == ("big-primary", "big")


def test_default_alias_constant():
    assert DEFAULT_AUTO_MODEL_ALIAS == "claude-proxy-auto"


def test_custom_alias_replaces_default():
    mm = ModelManager(FakeConfig(alias="my-opus-auto"))
    assert mm.is_auto_alias("my-opus-auto") is True
    assert mm.is_auto_alias("MY-OPUS-AUTO") is True
    assert mm.map_claude_model_to_openai("my-opus-auto") == ("big-primary", "big")
    # The default alias is no longer special: unknown names fall to big, but not via auto.
    assert mm.is_auto_alias("claude-proxy-auto") is False


@pytest.mark.parametrize(
    "alias", ["gpt-auto", "deepseek-auto", "o1-auto", "ep-auto", "sonnet-auto"]
)
def test_custom_alias_beats_passthrough_and_substring_rules(alias):
    mm = ModelManager(FakeConfig(alias=alias))
    assert mm.is_auto_alias(alias) is True
    assert mm.map_claude_model_to_openai(alias) == ("big-primary", "big")


@pytest.mark.parametrize(
    "name,expected",
    [
        ("claude-3-5-haiku-20241022", ("small-primary", "small")),
        ("claude-3-5-sonnet-20241022", ("mid-primary", "middle")),
        ("claude-3-opus-20240229", ("big-primary", "big")),
        ("gpt-4o", ("gpt-4o", "unknown")),
        ("o1-mini", ("o1-mini", "unknown")),
        ("deepseek-v3", ("deepseek-v3", "unknown")),
        ("ep-123", ("ep-123", "unknown")),
        ("doubao-pro", ("doubao-pro", "unknown")),
        ("totally-unknown", ("big-primary", "big")),
    ],
)
def test_existing_mappings_unchanged(mm, name, expected):
    assert mm.map_claude_model_to_openai(name) == expected
    assert mm.is_auto_alias(name) is False


def test_alias_follows_big_fallback(cfg, mm):
    cfg._active_big_idx = 1
    assert mm.map_claude_model_to_openai("claude-proxy-auto") == ("big-fallback", "big")


def test_disabled_alias_falls_through():
    mm = ModelManager(FakeConfig(enabled=False))
    assert mm.is_auto_alias("claude-proxy-auto") is False
    # Falls to the unknown-name path (BIG tier) without the auto branch.
    assert mm.map_claude_model_to_openai("claude-proxy-auto") == ("big-primary", "big")


def test_disabled_alias_with_passthrough_prefix_is_passthrough():
    mm = ModelManager(FakeConfig(alias="gpt-auto", enabled=False))
    assert mm.is_auto_alias("gpt-auto") is False
    assert mm.map_claude_model_to_openai("gpt-auto") == ("gpt-auto", "unknown")


@pytest.mark.parametrize("raw", ["False", "false", "0", "", "  ", "no", "OFF", " off "])
def test_parse_auto_enabled_false_values(raw):
    assert parse_auto_enabled(raw) is False


@pytest.mark.parametrize("raw", [None, "true", "True", "1", "yes", "on", "anything"])
def test_parse_auto_enabled_true_values(raw):
    assert parse_auto_enabled(raw) is True


def test_is_auto_alias_non_string(mm):
    assert mm.is_auto_alias(None) is False
