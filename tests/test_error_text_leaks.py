"""Exception text must not reach clients from /v1/messages/count_tokens or /test-connection.

Both routes used to return str(e): an exception message can echo request content or a key.
They now return fixed messages, and the detail is kept in the server log only.
"""

import asyncio
import logging

from fastapi.testclient import TestClient

from src.api import endpoints
from src.core.config import config as _config
from src.main import app

client = TestClient(app)

SECRET = "fake-key-LEAKME-12345678"
LEAK_PATH = "/Users/x/secret/path"


class _ExplodingMessage:
    """A message whose content access raises with a secret-bearing text."""

    @property
    def content(self):
        raise RuntimeError(f"internal detail {SECRET} {LEAK_PATH}")


class _Req:
    system = None

    def __init__(self):
        self.messages = [_ExplodingMessage()]


def test_count_tokens_handler_returns_fixed_detail(caplog):
    with caplog.at_level(logging.ERROR):
        try:
            asyncio.run(endpoints.count_tokens(_Req(), None))
        except Exception as exc:  # HTTPException raised by the handler
            assert getattr(exc, "status_code", None) == 500
            assert exc.detail == "Token counting failed"
            assert SECRET not in str(exc.detail)
            assert LEAK_PATH not in str(exc.detail)
        else:  # pragma: no cover - the handler must raise
            raise AssertionError("count_tokens did not fail on the exploding message")
    # the detail goes to the server log, which is where operators look
    assert SECRET in caplog.text


def test_test_connection_failure_does_not_return_exception_text(monkeypatch, caplog):
    async def _raise_with_secret():
        raise RuntimeError(f"upstream said: bad key {SECRET} at https://internal.example/v1")

    monkeypatch.setattr(_config, "get_next_client_async", _raise_with_secret)
    with caplog.at_level(logging.ERROR):
        res = client.get("/test-connection")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "failed"
    assert SECRET not in res.text
    assert "internal.example" not in res.text
    assert body["message"].startswith("Upstream connectivity check failed")
    # The log keeps the error TYPE only, never the message text
    assert "RuntimeError" in caplog.text
    assert SECRET not in caplog.text


def test_test_connection_exhausted_keys_message_is_fixed(monkeypatch):
    async def _none():
        return None

    monkeypatch.setattr(_config, "get_next_client_async", _none)
    res = client.get("/test-connection")
    assert res.status_code == 503
    assert res.json()["message"].startswith("Upstream connectivity check failed")


def test_endpoints_module_still_exposes_handlers():
    # guard against accidentally removing the routes this file exercises
    assert callable(endpoints.count_tokens)
    assert callable(endpoints.test_connection)
