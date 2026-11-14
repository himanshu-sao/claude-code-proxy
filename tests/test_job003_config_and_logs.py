"""Job-003 tests for Config parsing, converter clamping, cached context limits and the signal
log round trip into scripts/analyze_signal_log.py. Offline: no network, no ports, no real logs/.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.conversion import request_converter
from src.core import context_manager, signal_log
from src.core.config import DEFAULT_AUTO_MODEL_ALIAS, Config
from src.models.claude import ClaudeMessagesRequest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "analyze_signal_log.py"
CACHE_FILE = ROOT / "model_contexts_cache.json"


def _fresh_config(monkeypatch, **env):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    # src/__init__.py runs load_dotenv(override=True), which also walks up parent directories,
    # so any developer .env value for these must be cleared for the test to be deterministic.
    for var in (
        "AUTO_MODEL_ALIAS",
        "AUTO_MODEL_ENABLED",
        "ANTHROPIC_API_KEY",
        "MIN_TOKENS_LIMIT",
        "MAX_TOKENS_LIMIT",
    ):
        monkeypatch.delenv(var, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Config()


# --- (2) Config-level parsing ---------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   ", "\t"])
def test_empty_or_blank_alias_falls_back_to_default(monkeypatch, raw):
    cfg = _fresh_config(monkeypatch, AUTO_MODEL_ALIAS=raw)
    assert cfg.auto_model_alias == DEFAULT_AUTO_MODEL_ALIAS == "claude-proxy-auto"


def test_unset_alias_is_default(monkeypatch):
    cfg = _fresh_config(monkeypatch)
    assert cfg.auto_model_alias == "claude-proxy-auto"


def test_custom_alias_keeps_casing(monkeypatch):
    cfg = _fresh_config(monkeypatch, AUTO_MODEL_ALIAS="Team-Auto")
    assert cfg.auto_model_alias == "Team-Auto"


def test_unset_enabled_is_true(monkeypatch):
    assert _fresh_config(monkeypatch).auto_model_enabled is True


@pytest.mark.parametrize("raw", ["false", "0", "no", "off", "", "   "])
def test_enabled_false_like_values(monkeypatch, raw):
    assert _fresh_config(monkeypatch, AUTO_MODEL_ENABLED=raw).auto_model_enabled is False


@pytest.mark.parametrize("raw", ["flase", "fasle", "nope", "disabled", "10"])
def test_enabled_typo_stays_true(monkeypatch, raw):
    # Unknown spellings do not disable the alias: only the explicit false-like set does.
    assert _fresh_config(monkeypatch, AUTO_MODEL_ENABLED=raw).auto_model_enabled is True


# --- (7) converter clamping -----------------------------------------------------------------


class _StubManager:
    def __init__(self, model, tier):
        self._result = (model, tier)

    def map_claude_model_to_openai(self, _name):
        return self._result


def _convert(monkeypatch, max_tokens, model="gpt-4o-mini", tier="small", **env):
    cfg = _fresh_config(monkeypatch, **env)
    monkeypatch.setattr(request_converter, "config", cfg)
    # Keep the context-window step out of these tests: only clamping is under test here.
    monkeypatch.setattr(
        request_converter,
        "trim_messages_to_fit",
        lambda messages, name, req: (messages, req),
    )
    request = ClaudeMessagesRequest(
        model="claude-3-5-haiku-20241022",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": "hi"}],
    )
    return request_converter.convert_claude_to_openai(request, _StubManager(model, tier))


@pytest.mark.parametrize(
    "requested,expected",
    [(1, 100), (50, 100), (100, 100), (2000, 2000), (4096, 4096), (9999, 4096), (10**6, 4096)],
)
def test_max_tokens_clamped_to_min_and_max(monkeypatch, requested, expected):
    out = _convert(monkeypatch, requested)
    assert out["max_tokens"] == expected


def test_min_and_max_limits_come_from_env(monkeypatch):
    assert _convert(monkeypatch, 10, MIN_TOKENS_LIMIT="300")["max_tokens"] == 300
    assert _convert(monkeypatch, 5000, MAX_TOKENS_LIMIT="1000")["max_tokens"] == 1000


def test_clamp_is_applied_before_trim_sees_the_budget(monkeypatch):
    seen = []
    cfg = _fresh_config(monkeypatch)
    monkeypatch.setattr(request_converter, "config", cfg)

    def spy(messages, name, requested):
        seen.append(requested)
        return messages, requested

    monkeypatch.setattr(request_converter, "trim_messages_to_fit", spy)
    request = ClaudeMessagesRequest(
        model="claude-3-5-haiku-20241022",
        max_tokens=1,
        messages=[{"role": "user", "content": "hi"}],
    )
    request_converter.convert_claude_to_openai(request, _StubManager("gpt-4o-mini", "small"))
    assert seen == [cfg.min_tokens_limit]


# --- (7) cached context windows for the two MIDDLE_MODEL ids --------------------------------


def _cache_entries():
    raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {k: (v[0], v[1]) for k, v in raw.items() if isinstance(v, list) and len(v) == 2}


@pytest.fixture
def cached_limits(monkeypatch):
    """Read-only: install the repo cache into the in-memory table, never write the file."""
    monkeypatch.setattr(context_manager, "_DISCOVERED_LIMITS", _cache_entries())
    monkeypatch.setattr(context_manager, "_ENV_OVERRIDES", {})


@pytest.mark.parametrize(
    "model_id",
    ["mistralai/mistral-large-4-1t-a52b", "minimaxai/minimax-m3.1-flash"],
)
def test_trim_uses_cached_window_not_safe_default(cached_limits, model_id):
    # 262144 * 0.85 ~= 222.7k token budget. A 32k-window default would trim a ~150k-token
    # history, so untrimmed output proves the cached window is the one in force.
    text = "x" * (4 * 150_000)  # ~150k estimated tokens
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a" * 4},
        {"role": "user", "content": text},
        {"role": "user", "content": "last"},
    ]
    trimmed, clamped = context_manager.trim_messages_to_fit(messages, model_id, 4096)
    assert trimmed == messages
    assert clamped == 4096


@pytest.mark.parametrize(
    "model_id",
    ["mistralai/mistral-large-4-1t-a52b", "minimaxai/minimax-m3.1-flash"],
)
def test_output_cap_uses_cached_max_output(cached_limits, model_id):
    _, clamped = context_manager.trim_messages_to_fit(
        [{"role": "user", "content": "x"}], model_id, 100_000
    )
    assert clamped == 32768


def test_cached_window_is_trimmed_once_over_budget(cached_limits):
    # Above the cached budget the middle must be dropped, proving the 262144 window applies.
    text = "y" * (4 * 230_000)
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": text},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "tail"},
        {"role": "user", "content": "last"},
    ]
    trimmed, _ = context_manager.trim_messages_to_fit(
        messages, "minimaxai/minimax-m3.1-flash", 4096
    )
    assert len(trimmed) < len(messages)
    assert trimmed[0] == messages[0] and trimmed[-1] == messages[-1]


# --- (4) signal-log round trip into the analyzer -------------------------------------------


def _load_analyzer():
    spec = importlib.util.spec_from_file_location("analyze_signal_log", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analyzer = _load_analyzer()


@pytest.fixture
def emit_log(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "auto_signal.log"
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(path))
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    signal_log.reset_for_tests()
    yield path
    signal_log.reset_for_tests()


def _emit(first_text, sid, agent=False):
    headers = {"x-claude-code-session-id": sid}
    if agent:
        headers["x-claude-code-agent-id"] = "agent-1"
    request = ClaudeMessagesRequest(
        model="claude-proxy-auto",
        max_tokens=10,
        messages=[{"role": "user", "content": first_text}],
    )
    signal_log.emit_signal(request, headers, True)


def test_real_records_have_hash_shaped_keys(emit_log):
    _emit("hello", "sess-a")
    rec = json.loads(emit_log.read_text(encoding="utf-8").split("AUTOSIGNAL ", 1)[1])
    assert len(rec["sid_hash"]) == 8 and len(rec["fm_hash"]) == 8
    assert analyzer._is_hash(rec["sid_hash"])
    assert analyzer._is_hash(rec["fm_hash"])


@pytest.mark.parametrize("bad", ["", "ABCDEF12", "xyz", "0" * 65 + "1", None, 7])
def test_is_hash_rejects_non_hex_values(bad):
    assert analyzer._is_hash(bad) is False


def test_is_hash_accepts_upper_bound_length():
    assert analyzer._is_hash("a" * 64) is True
    assert analyzer._is_hash("a" * 65) is False


def test_analyzer_counts_real_records_and_reaches_a_verdict(emit_log):
    # 12 clean sessions, 3 main-thread turns each, plus one subagent turn per session.
    for i in range(12):
        for _ in range(3):
            _emit("unique opening %d" % i, "sess-%d" % i)
        _emit("subagent brief %d" % i, "sess-%d" % i, agent=True)

    records, skipped = analyzer.load_records([str(emit_log)])
    assert len(records) == 48 and skipped == 0
    with_both = [
        r
        for r in records
        if analyzer._is_hash(r.get("sid_hash")) and analyzer._is_hash(r.get("fm_hash"))
    ]
    assert len(with_both) == 48

    res = subprocess.run(
        [sys.executable, str(SCRIPT), str(emit_log)],
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(ROOT),
    )
    assert res.returncode == 0, res.stderr
    assert "sid_hash presence: 48 of 48 (100.0%)" in res.stdout
    assert "fm_hash presence:  48 of 48 (100.0%)" in res.stdout
    assert "Verdict: fm_hash is usable (thresholds met)" in res.stdout
    assert "constancy 100.0% (12 of 12 sessions, 36 main-thread turns)" in res.stdout


def test_analyzer_rejects_drifted_hash_length(emit_log, monkeypatch):
    # Guard for the failure mode this round trip exists to catch: if the emitter ever produced
    # a hash the analyzer does not accept, the verdict would silently go to zero. Simulate a
    # 65-char digest, which _HASH_RE (1 to 64 hex chars) must reject.
    monkeypatch.setattr(signal_log, "_hash", lambda prefix, text: "a" * 65)
    for i in range(12):
        _emit("opening %d" % i, "sess-%d" % i)
    records, _ = analyzer.load_records([str(emit_log)])
    assert records
    assert all(not analyzer._is_hash(r.get("sid_hash")) for r in records)
    assert all(not analyzer._is_hash(r.get("fm_hash")) for r in records)
