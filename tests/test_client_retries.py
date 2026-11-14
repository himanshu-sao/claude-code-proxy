"""Tests that MAX_RETRIES reaches the OpenAI SDK client (no real network, no real keys)."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi import HTTPException

from src.core.client import OpenAIClient


def _make_config(monkeypatch, value):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    if value is None:
        monkeypatch.delenv("MAX_RETRIES", raising=False)
    else:
        monkeypatch.setenv("MAX_RETRIES", value)
    import src.core.config as cfg

    return cfg.Config()


@pytest.mark.parametrize("n", [0, 2, 5])
def test_sdk_client_gets_max_retries(n):
    c = OpenAIClient("test-key", "http://127.0.0.1:1/v1", max_retries=n)
    assert c.client.max_retries == n


def test_azure_branch_gets_max_retries():
    c = OpenAIClient("test-key", "https://example.invalid", api_version="2024-02-01", max_retries=5)
    assert c.client.max_retries == 5


def test_default_is_two():
    assert OpenAIClient("test-key", "http://127.0.0.1:1/v1").client.max_retries == 2


@pytest.mark.parametrize("raw,expected", [(None, 2), ("0", 0), ("5", 5), ("-3", 0)])
def test_config_parsing(monkeypatch, raw, expected):
    assert _make_config(monkeypatch, raw).max_retries == expected


def test_config_garbage_raises(monkeypatch):
    with pytest.raises(ValueError):
        _make_config(monkeypatch, "abc")


def test_config_clients_carry_value(monkeypatch):
    cfg = _make_config(monkeypatch, "4")
    assert cfg.get_next_client().client.max_retries == 4

    async def _get():
        return await cfg.get_next_client_async()

    assert asyncio.run(_get()).client.max_retries == 4


class _Fake503(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        self.server.hits += 1
        body = b'{"error": {"message": "unavailable", "type": "server_error"}}'
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_upstream():
    srv = HTTPServer(("127.0.0.1", 0), _Fake503)
    srv.hits = 0
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.mark.parametrize("n", [0, 3])
def test_upstream_call_count(fake_upstream, n):
    url = "http://127.0.0.1:%d/v1" % fake_upstream.server_address[1]
    c = OpenAIClient("test-key", url, timeout=5, max_retries=n)
    req = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(HTTPException) as ei:
        asyncio.run(c.create_chat_completion(req))
    assert ei.value.status_code == 503
    assert fake_upstream.hits == n + 1
