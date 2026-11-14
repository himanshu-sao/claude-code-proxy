"""Exhausted API keys must surface as a real HTTP 429 with an integer Retry-After.

Covers both the streaming and non-streaming paths, the async-only client
getter inside request handlers (the sync getter sleeps and would block the
event loop), and the log file handler opening in append mode.
"""

import logging
import time

import pytest
from fastapi.testclient import TestClient

from src.api import endpoints
from src.core.config import config as _config
from src.main import app

client = TestClient(app)


def _body(stream: bool):
    return {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 100,
        "stream": stream,
        "messages": [{"role": "user", "content": "hello"}],
    }


@pytest.fixture
def exhausted(monkeypatch):
    """Simulate every key being over its RPM limit, and fail loudly if the sync getter is used."""

    async def _none():
        return None

    def _forbidden(*_a, **_k):
        raise AssertionError("sync get_next_client must not be called from an async handler")

    monkeypatch.setattr(_config, "get_next_client_async", _none)
    monkeypatch.setattr(_config, "get_next_client", _forbidden)
    monkeypatch.setattr(_config, "seconds_until_key_available", lambda: 7)
    monkeypatch.setattr(endpoints, "_write_last_model", lambda tier, model: None)


@pytest.mark.parametrize("stream", [False, True])
def test_exhausted_keys_return_429_with_retry_after(exhausted, stream):
    res = client.post("/v1/messages", json=_body(stream))
    assert res.status_code == 429
    assert res.headers["retry-after"] == "7"
    assert res.json()["detail"].startswith("All API keys exhausted")


def test_retry_after_is_integer_within_1_and_60():
    value = _config.seconds_until_key_available()
    assert isinstance(value, int)
    assert 1 <= value <= 60


def test_retry_after_capped_at_60_when_windows_are_fresh(monkeypatch):
    now = time.time()
    fresh = {k: {"count": 0, "window_start": now} for k in _config._provider_usage}
    monkeypatch.setattr(_config, "_provider_usage", fresh)
    assert _config.seconds_until_key_available() == 60


def test_no_blocking_sleep_when_keys_exhausted(monkeypatch):
    """The async getter must return None immediately, never sleep."""
    import asyncio

    def _no_sleep(_seconds):
        raise AssertionError("time.sleep called on the request path")

    monkeypatch.setattr(time, "sleep", _no_sleep)
    monkeypatch.setattr(
        _config, "get_next_provider", lambda: (_ for _ in ()).throw(RuntimeError("x"))
    )
    started = time.monotonic()
    result = asyncio.run(_config.get_next_client_async())
    assert result is None
    assert time.monotonic() - started < 0.5


def test_file_log_handler_appends_instead_of_truncating():
    file_handlers = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.FileHandler) and h.baseFilename.endswith("proxy.log")
    ]
    assert file_handlers, "proxy.log file handler should be configured"
    assert all(h.mode == "a" for h in file_handlers)
