"""/health is unauthenticated, so it must not expose any part of an upstream API key.

Keys are reported by their 1-based position in OPENAI_API_KEY instead of a key prefix, and the
rate-limit log line uses the same index.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from src.core.config import config as _config
from src.main import app

client = TestClient(app)

KEYS = ["fake-key-alpha-1234567890", "fake-key-bravo-0987654321"]


@pytest.fixture
def two_keys(monkeypatch):
    providers = [{"api_key": k, "base_url": "https://upstream.invalid/v1"} for k in KEYS]
    usage = {k: {"count": 0, "window_start": 0.0} for k in KEYS}
    monkeypatch.setattr(_config, "providers", providers)
    monkeypatch.setattr(_config, "_provider_usage", usage)
    monkeypatch.setattr(_config, "_provider_penalties", {})
    return providers


def test_health_reports_key_index_not_key_material(two_keys):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    entries = body["rpm_info"]
    assert [e["key_index"] for e in entries] == [1, 2]
    assert all("key_prefix" not in e for e in entries)
    for key in KEYS:
        # no prefix of any length >= 4 from either key appears anywhere in the response
        for n in range(4, len(key) + 1):
            assert key[:n] not in res.text
    assert body["total_configured_keys"] == 2


def test_health_still_reports_usage_and_penalty(two_keys, monkeypatch):
    import time

    now = time.time()
    _config._provider_usage[KEYS[1]] = {"count": 3, "window_start": now}
    _config._provider_penalties[KEYS[1]] = now + 30
    entries = client.get("/health").json()["rpm_info"]
    second = next(e for e in entries if e["key_index"] == 2)
    assert second["requests_this_minute"] == 3
    assert 25 <= second["penalty_remaining_seconds"] <= 30


def test_rate_limit_log_uses_index_not_prefix(two_keys, caplog):
    with caplog.at_level(logging.WARNING, logger="config"):
        _config.report_rate_limit(KEYS[1])
    assert "key #2" in caplog.text
    for key in KEYS:
        assert key[:8] not in caplog.text


def test_rate_limit_log_for_unknown_key_does_not_leak(two_keys, caplog):
    with caplog.at_level(logging.WARNING, logger="config"):
        _config.report_rate_limit("fake-key-unknown-555555")
    assert "key #?" in caplog.text
    assert "fake-key" not in caplog.text
