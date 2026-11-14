"""Error contract for POST /v1/messages (slice C of 005-error-contract).

Covers the non-stream path and the stream path before the first chunk: real HTTP status, the
Anthropic envelope, forwarded headers, our own 429, the first-chunk priming helper and the
event loop staying free while keys are exhausted. Offline: patched SDK calls, plus tiny local
HTTP servers on 127.0.0.1 (as in tests/test_client_retries.py).
"""

import asyncio
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from src.api import endpoints
from src.core import client as client_module
from src.core.client import OpenAIClient
from src.core.config import Config
from src.core.config import config as _config
from src.core.errors import PROMPT_TOO_LONG_PREFIX, error_type_for_status
from src.main import app

client = TestClient(app)

TIER_MODEL = "claude-3-opus-20240229"
OWN_429 = "All API keys exhausted. Please wait before trying again."
MODES = pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
_REQ = httpx.Request("POST", "https://upstream.invalid/v1/chat/completions")


@pytest.fixture(autouse=True)
def _no_client_key(monkeypatch):
    monkeypatch.setattr(_config, "anthropic_api_key", None)
    monkeypatch.setattr(endpoints, "_write_last_model", lambda tier, model: None)


def _body(stream=False):
    return {
        "model": TIER_MODEL,
        "max_tokens": 100,
        "stream": stream,
        "messages": [{"role": "user", "content": "hello"}],
    }


_ERROR_CLASSES = {
    400: openai.BadRequestError,
    401: openai.AuthenticationError,
    403: openai.PermissionDeniedError,
    404: openai.NotFoundError,
    422: openai.UnprocessableEntityError,
    429: openai.RateLimitError,
}


def _api_error(status, message, headers=None):
    response = httpx.Response(status, headers=headers or {}, request=_REQ)
    cls = _ERROR_CLASSES.get(status)
    if cls is None:
        cls = openai.InternalServerError if status >= 500 else openai.APIStatusError
    return cls(message, response=response, body=None)


@pytest.fixture
def failing(monkeypatch):
    """Real OpenAIClient on the global config whose SDK create() raises; returns an installer.

    A fresh OpenAIClient is used per install, so a 429 never leaks cooldown between cases
    (the stubbed getter does not go through the provider pool).
    """
    failures, rate_limits = [], []
    monkeypatch.setattr(_config, "report_model_failure", lambda m, t: failures.append((m, t)))
    monkeypatch.setattr(_config, "report_rate_limit", lambda k: rate_limits.append(k))
    seen = {"calls": []}

    def _install(exc):
        oc = OpenAIClient("upstream-key", "https://upstream.invalid/v1")

        async def _raise(**kwargs):
            raise exc

        monkeypatch.setattr(oc.client.chat.completions, "create", _raise)

        async def _next(*, stream=False):
            seen["calls"].append(stream)
            return oc

        monkeypatch.setattr(_config, "get_next_client_async", _next)
        return oc

    _install.failures = failures
    _install.rate_limits = rate_limits
    _install.seen = seen
    return _install


def _post(stream, **kw):
    return client.post("/v1/messages", json=_body(stream), **kw)


# --- G1: status matrix, same status and body on both paths ----------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 500, 502, 503, 529])
def test_status_and_body_identical_on_stream_and_non_stream(failing, status):
    message = "upstream says no (%d)" % status
    results = []
    for stream in (False, True):
        failing(_api_error(status, message))
        results.append(_post(stream))
    plain, streamed = results
    for res in results:
        assert res.status_code == status
        assert res.headers["content-type"].startswith("application/json")
        body = res.json()
        assert body["type"] == "error"
        assert body["error"]["type"] == error_type_for_status(status)
        assert body["error"]["message"] == message
    assert plain.json() == streamed.json()


@MODES
def test_context_length_400_carries_prefix(failing, stream):
    message = "This model's maximum context length is 8192 tokens."
    failing(_api_error(400, message))
    res = _post(stream)
    assert res.status_code == 400
    assert res.json()["error"]["message"] == PROMPT_TOO_LONG_PREFIX + message
    assert res.headers["content-type"].startswith("application/json")


# --- G2 / G7 / edge 2: 429 and retry-after --------------------------------------------------


@MODES
def test_upstream_429_with_retry_after_is_forwarded(failing, stream):
    failing(_api_error(429, "slow down", {"retry-after": "5"}))
    res = _post(stream)
    assert res.status_code == 429
    assert res.headers["retry-after"] == "5"
    assert res.json()["error"] == {"type": "rate_limit_error", "message": "slow down"}


@MODES
def test_upstream_429_without_retry_after_gets_none(failing, stream):
    failing(_api_error(429, "slow down"))
    res = _post(stream)
    assert res.status_code == 429
    assert "retry-after" not in res.headers
    assert res.json()["error"]["type"] == "rate_limit_error"


@MODES
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("120", "120"),
        ("3600", "3600"),
        ("0", "0"),
        ("Wed, 21 Oct 2015 07:28:00 GMT", None),
        ("abc", None),
        ("1.5", None),
        ("-5", None),
    ],
)
def test_upstream_retry_after_forwarding_rules(failing, stream, raw, expected):
    failing(_api_error(429, "slow down", {"retry-after": raw}))
    res = _post(stream)
    assert res.status_code == 429
    assert res.headers.get("retry-after") == expected


@MODES
@pytest.mark.parametrize("stubbed,expected", [(7, "7"), (0, "1"), (999, "60")])
def test_own_429_retry_after_is_clamped_to_1_60(monkeypatch, stream, stubbed, expected):
    async def _none(*, stream=False):
        return None

    monkeypatch.setattr(_config, "get_next_client_async", _none)
    monkeypatch.setattr(_config, "seconds_until_key_available", lambda: stubbed)
    res = _post(stream)
    assert res.status_code == 429
    assert res.headers["retry-after"] == expected
    assert res.json()["error"] == {"type": "rate_limit_error", "message": OWN_429}


# --- edge 3: x-should-retry -----------------------------------------------------------------


@MODES
@pytest.mark.parametrize("value", ["true", "false", None])
def test_x_should_retry_passes_through(failing, stream, value):
    headers = {"x-should-retry": value} if value else {}
    failing(_api_error(503, "down", headers))
    res = _post(stream)
    assert res.status_code == 503
    assert res.headers.get("x-should-retry") == value


# --- G8: exhausted keys with the real Config ------------------------------------------------


def _use_config(monkeypatch, cfg):
    monkeypatch.setattr(endpoints, "config", cfg)
    monkeypatch.setattr(client_module, "config", cfg)


def _real_config(monkeypatch, keys="key-aaaaaaaa", base_url=None, **env):
    monkeypatch.setenv("OPENAI_API_KEY", keys)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    if base_url:
        monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    cfg = Config()
    _use_config(monkeypatch, cfg)
    return cfg


def _forbid_sync_getter(cfg, monkeypatch):
    def _forbidden(*_a, **_k):
        raise AssertionError("sync get_next_client must not be called from a request handler")

    monkeypatch.setattr(cfg, "get_next_client", _forbidden)


@MODES
def test_exhausted_real_config_returns_429_not_500(monkeypatch, stream):
    cfg = _real_config(monkeypatch)
    cfg._rpm_limit = 0
    _forbid_sync_getter(cfg, monkeypatch)
    res = _post(stream)
    assert res.status_code == 429
    body = res.json()
    assert body is not None
    assert body["error"] == {"type": "rate_limit_error", "message": OWN_429}
    assert 1 <= int(res.headers["retry-after"]) <= 60


@MODES
def test_getter_returning_none_returns_429(monkeypatch, stream):
    async def _none(*, stream=False):
        return None

    monkeypatch.setattr(_config, "get_next_client_async", _none)
    monkeypatch.setattr(
        _config, "get_next_client", lambda: (_ for _ in ()).throw(AssertionError("sync"))
    )
    res = _post(stream)
    assert res.status_code == 429
    assert res.json()["error"]["message"] == OWN_429


# --- G9: the event loop stays free while keys are exhausted ---------------------------------


async def test_health_answers_fast_while_keys_are_exhausted(monkeypatch):
    """Real Config, real sync getter left in place: if a handler used it, it would sleep 2 s."""
    cfg = _real_config(monkeypatch)
    cfg._rpm_limit = 0
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        assert (await ac.get("/health")).status_code == 200  # warm up imports and routing

        async def _health():
            started = time.perf_counter()
            res = await ac.get("/health")
            return res.status_code, time.perf_counter() - started

        posts = [
            asyncio.ensure_future(ac.post("/v1/messages", json=_body(stream=i % 2 == 0)))
            for i in range(6)
        ]
        # Let the POSTs reach their handlers first. A handler that blocks the loop (the sync
        # getter sleeps up to 2 s) stretches this short sleep far past its 50 ms.
        before = time.perf_counter()
        await asyncio.sleep(0.05)
        assert time.perf_counter() - before < 0.15
        status, elapsed = await _health()
        results = await asyncio.gather(*posts)
    assert status == 200
    assert elapsed < 0.1
    assert [r.status_code for r in results] == [429] * 6


# --- local fake upstream (G10, edge 15, edge 4) ---------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        srv = self.server
        srv.hits += 1
        self.send_response(srv.status)
        self.send_header("Content-Type", srv.content_type)
        self.send_header("Content-Length", str(len(srv.payload)))
        self.end_headers()
        self.wfile.write(srv.payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_upstream():
    servers = []

    def _make(status=503, payload=None, content_type="application/json"):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        srv.daemon_threads = True
        srv.hits = 0
        srv.status = status
        srv.content_type = content_type
        srv.payload = (
            payload
            if payload is not None
            else b'{"error": {"message": "unavailable", "type": "server_error"}}'
        )
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        srv.url = "http://127.0.0.1:%d/v1" % srv.server_address[1]
        return srv

    yield _make
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def test_stream_one_upstream_hit_non_stream_retries(monkeypatch, fake_upstream):
    srv = fake_upstream(503)
    _real_config(monkeypatch, base_url=srv.url, STREAM_MAX_RETRIES="0", MAX_RETRIES="2")

    res = _post(True)
    assert res.status_code == 503
    assert srv.hits == 1

    srv.hits = 0
    res = _post(False)
    assert res.status_code == 503
    assert srv.hits == 3
    assert res.json()["error"]["message"] == "unavailable"


@MODES
def test_html_502_body_is_still_valid_anthropic_json(monkeypatch, fake_upstream, stream):
    srv = fake_upstream(502, b"<html>Bad Gateway</html>", "text/html")
    _real_config(monkeypatch, base_url=srv.url, STREAM_MAX_RETRIES="0", MAX_RETRIES="0")
    res = _post(stream)
    assert res.status_code == 502
    body = res.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "api_error"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# --- edge 4: first chunk never arrives ------------------------------------------------------


@MODES
def test_sdk_timeout_is_a_real_http_500_before_any_body(failing, stream):
    """No extra timer exists: a hang is bounded by the SDK's REQUEST_TIMEOUT, which raises
    APITimeoutError. That maps to HTTP 500 api_error before any byte, so Claude Code retries."""
    failing(openai.APITimeoutError(request=_REQ))
    res = _post(stream)
    assert res.status_code == 500
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["error"]["type"] == "api_error"


def test_real_socket_that_never_answers_gives_500(monkeypatch):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    held = []
    stop = threading.Event()

    def _accept():
        listener.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(listener.accept()[0])
            except OSError:
                continue

    threading.Thread(target=_accept, daemon=True).start()
    try:
        url = "http://127.0.0.1:%d/v1" % listener.getsockname()[1]
        _real_config(
            monkeypatch, base_url=url, REQUEST_TIMEOUT="1", STREAM_MAX_RETRIES="0", MAX_RETRIES="0"
        )
        started = time.monotonic()
        res = _post(True)
        assert time.monotonic() - started < 4
        assert res.status_code == 500
        assert res.json()["error"]["type"] == "api_error"
    finally:
        stop.set()
        for conn in held:
            conn.close()
        listener.close()


# --- edge 5: _await_first_chunk cleanup -----------------------------------------------------


class _Http:
    """Fake Request: reports a disconnect from the second poll on (or never)."""

    def __init__(self, disconnect=True):
        self.disconnect = disconnect
        self.polls = 0

    async def is_disconnected(self):
        self.polls += 1
        return self.disconnect and self.polls > 1


@pytest.fixture
def hanging(monkeypatch):
    monkeypatch.setattr(endpoints, "FIRST_CHUNK_POLL_SECONDS", 0.01)
    failures = []
    monkeypatch.setattr(_config, "report_model_failure", lambda m, t: failures.append((m, t)))
    oc = OpenAIClient("upstream-key", "https://upstream.invalid/v1")
    state = {"cancelled": False, "started": asyncio.Event()}

    async def _hang(**kwargs):
        state["started"].set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr(oc.client.chat.completions, "create", _hang)
    gen = oc.create_chat_completion_stream({"model": "m", "messages": []}, "rid-1", "big")
    return oc, gen, state, failures


def _assert_clean(oc, state, failures):
    assert state["cancelled"] is True
    assert oc.active_requests == {}
    leftovers = asyncio.all_tasks() - {asyncio.current_task()}
    assert leftovers == set()
    assert failures == []


async def test_disconnect_while_waiting_cancels_upstream_and_cleans_up(hanging):
    oc, gen, state, failures = hanging
    with pytest.raises(endpoints._ClientGone):
        await endpoints._await_first_chunk(gen, _Http(disconnect=True), oc, "rid-1")
    _assert_clean(oc, state, failures)


async def test_handler_cancellation_cleans_up_and_is_not_a_model_failure(hanging):
    oc, gen, state, failures = hanging
    task = asyncio.ensure_future(
        endpoints._await_first_chunk(gen, _Http(disconnect=False), oc, "rid-1")
    )
    await state["started"].wait()
    assert "rid-1" in oc.active_requests
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _assert_clean(oc, state, failures)


# --- edge 9 / edge 10: multi-key and exhausted-after-429 ------------------------------------


class _Obj:
    def __init__(self, data):
        self._data = data

    def model_dump(self):
        return self._data


_CHAT = {
    "id": "chatcmpl-x",
    "choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
}
_CHUNK = {"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}


def _patch_sdk(monkeypatch, bad_keys):
    """Patch the SDK create(): keys in bad_keys get a 429, others succeed. Returns call list."""
    calls = []

    async def _aiter():
        yield _Obj(_CHUNK)

    async def _create(self, **kwargs):
        key = self._client.api_key
        calls.append(key)
        if key in bad_keys:
            raise _api_error(429, "key limited")
        return _aiter() if kwargs.get("stream") else _Obj(_CHAT)

    from openai.resources.chat.completions import AsyncCompletions

    monkeypatch.setattr(AsyncCompletions, "create", _create)
    return calls


@MODES
def test_one_key_429s_next_key_serves(monkeypatch, stream):
    cfg = _real_config(monkeypatch, keys="key-aaaaaaaa,key-bbbbbbbb")
    calls = _patch_sdk(monkeypatch, {"key-aaaaaaaa"})
    assert _post(stream).status_code == 429
    assert _post(stream).status_code == 200
    assert set(cfg._provider_penalties) == {"key-aaaaaaaa"}
    assert _post(stream).status_code == 200
    assert calls == ["key-aaaaaaaa", "key-bbbbbbbb", "key-bbbbbbbb"]


@MODES
def test_single_key_after_429_gets_own_429_without_upstream_call(monkeypatch, stream):
    _real_config(monkeypatch, keys="key-aaaaaaaa")
    calls = _patch_sdk(monkeypatch, {"key-aaaaaaaa"})
    first = _post(stream)
    assert first.status_code == 429
    assert first.json()["error"]["message"] == "key limited"
    assert len(calls) == 1
    second = _post(stream)
    assert second.status_code == 429
    assert second.json()["error"] == {"type": "rate_limit_error", "message": OWN_429}
    assert 1 <= int(second.headers["retry-after"]) <= 60
    assert len(calls) == 1


# --- stubs and error shaping ----------------------------------------------------------------


class _StubClient:
    active_requests: dict = {}

    async def create_chat_completion(self, request, request_id=None, model_tier=None):
        return dict(_CHAT)

    async def create_chat_completion_stream(self, request, request_id=None, model_tier=None):
        yield "data: " + json.dumps(_CHUNK)
        yield "data: [DONE]"

    def cancel_request(self, request_id):
        pass


@pytest.fixture
def recording(monkeypatch):
    calls = []

    async def _next(**kwargs):
        calls.append(kwargs)
        return _StubClient()

    monkeypatch.setattr(_config, "get_next_client_async", _next)
    return calls


def test_stream_requests_stream_client_and_non_stream_does_not(recording):
    assert _post(False).status_code == 200
    assert recording == [{}]
    res = _post(True)
    assert res.status_code == 200
    assert "message_start" in res.text and "hi" in res.text
    assert recording == [{}, {"stream": True}]


def test_empty_stream_still_returns_a_response(monkeypatch, recording):
    async def _nothing(self, request, request_id=None, model_tier=None):
        return
        yield

    monkeypatch.setattr(_StubClient, "create_chat_completion_stream", _nothing)
    res = _post(True)
    assert res.status_code == 200
    assert "message_start" in res.text


@MODES
def test_internal_bug_is_a_generic_500_without_the_message(monkeypatch, recording, stream):
    def _boom(*a, **k):
        raise ValueError("boom")

    monkeypatch.setattr(
        endpoints,
        "convert_claude_to_openai" if stream else "convert_openai_to_claude_response",
        _boom,
    )
    res = _post(stream)
    assert res.status_code == 500
    assert res.json() == {
        "type": "error",
        "error": {"type": "api_error", "message": "Internal server error"},
    }
    assert "boom" not in res.text
