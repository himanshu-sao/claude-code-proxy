"""Offline tests for src/core/errors.py and the OpenAIClient error paths built on it."""

import json
import subprocess
import sys

import httpx
import pytest
from fastapi import HTTPException
from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from src.core import client as client_module
from src.core.client import OpenAIClient
from src.core.config import Config
from src.core.errors import (
    MappedError,
    UpstreamError,
    UpstreamHTTPError,
    counts_as_model_failure,
    error_envelope,
    error_json,
    map_upstream_error,
)

PREFIX = "capability_rejected: prompt_too_long "
REQ = httpx.Request("POST", "https://upstream.invalid/v1/chat/completions")


def _err(status, message="upstream says no", headers=None, body=None, cls=None, code=None):
    cls = cls or APIStatusError
    resp = httpx.Response(status, headers=headers or {}, request=REQ)
    exc = cls(message, response=resp, body=body)
    if code is not None:
        exc.code = code
    return exc


# --- mapping table -----------------------------------------------------------------------

_TABLE = [
    (400, "invalid_request_error"),
    (401, "authentication_error"),
    (403, "permission_error"),
    (404, "not_found_error"),
    (413, "request_too_large"),
    (422, "invalid_request_error"),
    (429, "rate_limit_error"),
    (500, "api_error"),
    (502, "api_error"),
    (503, "api_error"),
    (529, "overloaded_error"),
]


@pytest.mark.parametrize("status,etype", _TABLE)
def test_mapping_table(status, etype):
    m = map_upstream_error(_err(status, "plain upstream text"))
    assert isinstance(m, MappedError)
    assert (m.status, m.error_type, m.message) == (status, etype, "plain upstream text")
    status_, etype_, message_, headers_, retryable_, counts_ = m  # 6-tuple unpack
    assert (status_, etype_, message_) == (status, etype, "plain upstream text")


def test_message_taken_from_body_error_message_then_body_message():
    m = map_upstream_error(_err(500, "sdk text", body={"error": {"message": "from body"}}))
    assert m.message == "from body"
    m = map_upstream_error(_err(500, "sdk text", body={"message": "top level"}))
    assert m.message == "top level"
    m = map_upstream_error(_err(500, "sdk text", body={"error": {"message": "  "}}))
    assert m.message == "sdk text"


@pytest.mark.parametrize("message", ["", "   ", "\n"])
def test_empty_message_falls_back(message):
    assert map_upstream_error(_err(502, message)).message == "Upstream error (HTTP 502)"


def test_missing_status_code_defaults():
    assert map_upstream_error(APIConnectionError(request=REQ)).status == 500
    auth = AuthenticationError("x", response=httpx.Response(401, request=REQ), body=None)
    auth.status_code = None
    assert map_upstream_error(auth).status == 401
    rl = RateLimitError("x", response=httpx.Response(429, request=REQ), body=None)
    rl.status_code = None
    assert map_upstream_error(rl).status == 429


def test_non_api_error_maps_to_500():
    m = map_upstream_error(ValueError("boom"))
    assert (m.status, m.error_type, m.message) == (500, "api_error", "Unexpected error: boom")
    assert m.headers == {}


def test_other_statuses_keep_status():
    assert map_upstream_error(_err(418)).error_type == "invalid_request_error"
    assert map_upstream_error(_err(418)).status == 418
    assert map_upstream_error(_err(504)).error_type == "api_error"


# --- headers -----------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "5", "120", "3600"])
def test_integer_retry_after_forwarded(value):
    m = map_upstream_error(_err(429, headers={"Retry-After": value}))
    assert m.headers == {"retry-after": value}


@pytest.mark.parametrize("value", ["Wed, 21 Oct 2026 07:28:00 GMT", "abc", "-5", "1.5", ""])
def test_non_integer_retry_after_dropped(value):
    assert (
        "retry-after" not in map_upstream_error(_err(429, headers={"Retry-After": value})).headers
    )


def test_passthrough_headers_and_unrelated_dropped():
    m = map_upstream_error(
        _err(
            503,
            headers={
                "X-Should-Retry": "true",
                "X-Request-Id": "req_1",
                "Request-Id": "req_2",
                "Anthropic-Ratelimit-Unified-Status": "limited",
                "Set-Cookie": "a=b",
                "Content-Type": "text/html",
            },
        )
    )
    assert m.headers == {
        "x-should-retry": "true",
        "x-request-id": "req_1",
        "request-id": "req_2",
        "anthropic-ratelimit-unified-status": "limited",
    }


def test_retryable_rules():
    assert map_upstream_error(_err(503)).retryable is True
    assert map_upstream_error(_err(429)).retryable is True
    assert map_upstream_error(_err(408)).retryable is True
    assert map_upstream_error(_err(400)).retryable is False
    assert map_upstream_error(_err(503, headers={"x-should-retry": "false"})).retryable is False
    assert map_upstream_error(_err(400, headers={"x-should-retry": "true"})).retryable is True


# --- redaction (edge 14) -----------------------------------------------------------------


def test_api_key_redacted():
    m = map_upstream_error(_err(401, "Incorrect API key provided: fake-key-1234."), "fake-key-1234")
    assert "fake-key-1234" not in m.message
    assert m.message == "Incorrect API key provided: [redacted]."
    assert map_upstream_error(_err(401, "abc"), "").message == "abc"
    assert map_upstream_error(_err(401, "abc"), None).message == "abc"


# --- prompt too long (edge 13) -------------------------------------------------------------

_TRIGGERS = [
    "context_length_exceeded",
    "maximum context length is 8192",
    "string too long",
    "exceeds the context window",
    "too many tokens",
    "CONTEXT WINDOW overflow",
]


@pytest.mark.parametrize("text", _TRIGGERS)
@pytest.mark.parametrize("status", [400, 413])
def test_prompt_too_long_prefix(text, status):
    cls = BadRequestError if status == 400 else APIStatusError
    m = map_upstream_error(_err(status, text, cls=cls))
    assert m.message == PREFIX + text


def test_prompt_too_long_by_code_and_body():
    m = map_upstream_error(_err(400, "nope", code="context_length_exceeded", cls=BadRequestError))
    assert m.message == PREFIX + "nope"


def test_no_prefix_for_other_cases():
    assert map_upstream_error(_err(400, "bad request")).message == "bad request"
    assert map_upstream_error(_err(503, "context window")).message == "context window"
    assert map_upstream_error(_err(401, "context window")).message == "context window"


# --- JSON (G5) ---------------------------------------------------------------------------


def test_error_json_round_trips():
    msg = 'say "hi"\nline2\\ é \n\nevent: message_stop'
    parsed = json.loads(error_json("api_error", msg))
    assert parsed == error_envelope("api_error", msg)
    assert parsed["error"]["message"] == msg
    assert parsed["type"] == "error"


def test_client_has_no_fstring_json():
    import inspect

    src = inspect.getsource(client_module)
    assert "data: {{" not in src
    assert not hasattr(OpenAIClient, "classify_openai_error")


def test_errors_module_imports_without_env_or_config():
    code = (
        "import sys; import src.core.errors; sys.exit(1 if 'src.core.config' in sys.modules else 0)"
    )
    env = {"PATH": "", "PYTHONPATH": "."}
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# --- counts_as_model_failure -------------------------------------------------------------


@pytest.mark.parametrize("status", [429, 503])
def test_counts_for_status(status):
    assert counts_as_model_failure(status, "anything") is True


@pytest.mark.parametrize(
    "text",
    [
        "rate_limit hit",
        "server overloaded",
        "no capacity",
        "model foo not found",
        "model x unavailable",
        "the model does not exist",
    ],
)
def test_counts_for_text(text):
    assert counts_as_model_failure(400, text) is True


def test_plain_400_does_not_count():
    assert counts_as_model_failure(400, "bad request") is False
    assert counts_as_model_failure(401, "invalid key") is False


# --- client integration (G11, edge 8, edge 11) -----------------------------------------------


@pytest.fixture
def failures(monkeypatch):
    calls, limits = [], []
    monkeypatch.setattr(
        client_module.config, "report_model_failure", lambda m, t: calls.append((m, t))
    )
    monkeypatch.setattr(client_module.config, "report_rate_limit", lambda k: limits.append(k))
    return calls, limits


def _make_client(monkeypatch, exc, **kwargs):
    oc = OpenAIClient("fake-key-1234", "https://upstream.invalid/v1", **kwargs)

    async def _raise(**kw):
        raise exc

    monkeypatch.setattr(oc.client.chat.completions, "create", _raise)
    return oc


REQUEST = {"model": "m1", "messages": []}


async def _drain(gen):
    async for _ in gen:
        pass


@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
@pytest.mark.parametrize("status,expected", [(503, 1), (400, 0), (401, 0)])
async def test_reporting_once_per_call(monkeypatch, failures, stream, status, expected):
    calls, _ = failures
    cls = {400: BadRequestError, 401: AuthenticationError}.get(status, APIStatusError)
    oc = _make_client(monkeypatch, _err(status, "boom", cls=cls))
    with pytest.raises(UpstreamError):
        if stream:
            await _drain(oc.create_chat_completion_stream(dict(REQUEST), "r1", "big"))
        else:
            await oc.create_chat_completion(dict(REQUEST), "r1", "big")
    assert len(calls) == expected
    assert oc.active_requests == {}


@pytest.mark.parametrize("api_version", [None, "2024-02-01"], ids=["openai", "azure"])
async def test_non_stream_exposure(monkeypatch, failures, api_version):
    exc = _err(429, "slow down", headers={"retry-after": "120", "x-foo": "1"}, cls=RateLimitError)
    kwargs = {"api_version": api_version} if api_version else {}
    oc = _make_client(monkeypatch, exc, **kwargs)
    with pytest.raises(UpstreamHTTPError) as ei:
        await oc.create_chat_completion(dict(REQUEST), None, "big")
    e = ei.value
    assert isinstance(e, HTTPException)
    assert (e.status_code, e.detail) == (429, "slow down")
    assert e.headers == {"retry-after": "120"}
    assert e.mapped == map_upstream_error(exc, "fake-key-1234")
    assert failures[1] == ["fake-key-1234"]


@pytest.mark.parametrize("api_version", [None, "2024-02-01"], ids=["openai", "azure"])
async def test_stream_exposure(monkeypatch, failures, api_version):
    exc = _err(503, "down", headers={"x-should-retry": "true"})
    kwargs = {"api_version": api_version} if api_version else {}
    oc = _make_client(monkeypatch, exc, **kwargs)
    with pytest.raises(UpstreamError) as ei:
        await _drain(oc.create_chat_completion_stream(dict(REQUEST), None, "big"))
    assert not isinstance(ei.value, HTTPException)
    assert ei.value.mapped == map_upstream_error(exc, "fake-key-1234")
    assert str(ei.value) == "down"


async def test_unexpected_exception_maps_to_500(monkeypatch, failures):
    oc = _make_client(monkeypatch, RuntimeError("kaboom"))
    with pytest.raises(UpstreamHTTPError) as ei:
        await oc.create_chat_completion(dict(REQUEST), None, "big")
    assert (ei.value.status_code, ei.value.detail) == (500, "Unexpected error: kaboom")
    assert failures[0] == []


async def test_key_redacted_in_client_error(monkeypatch, failures):
    oc = _make_client(monkeypatch, _err(401, "bad key fake-key-1234", cls=AuthenticationError))
    with pytest.raises(UpstreamHTTPError) as ei:
        await oc.create_chat_completion(dict(REQUEST), None, "big")
    assert "fake-key-1234" not in ei.value.detail


@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
async def test_model_fallback_switch_mid_sequence(monkeypatch, stream):
    monkeypatch.setenv("BIG_MODEL", "a,b")
    monkeypatch.setenv("MODEL_FAILURE_THRESHOLD", "3")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-1234")
    cfg = Config()
    monkeypatch.setattr(client_module, "config", cfg)
    reported = []
    real = cfg.report_model_failure

    def spy(model, tier):
        reported.append(model)
        real(model, tier)

    monkeypatch.setattr(cfg, "report_model_failure", spy)
    oc = _make_client(monkeypatch, _err(503, "down"))
    assert cfg.get_active_model("big") == "a"
    for _ in range(4):
        req = {"model": cfg.get_active_model("big"), "messages": []}
        with pytest.raises(UpstreamError):
            if stream:
                await _drain(oc.create_chat_completion_stream(req, None, "big"))
            else:
                await oc.create_chat_completion(req, None, "big")
        if len(reported) == 3:
            assert cfg.get_active_model("big") == "b"
    assert reported == ["a", "a", "a", "b"]


# --- round 1 rework --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["٣", "5٣", "12345678901", "1 2", "+5", "５"])
def test_retry_after_strict_ascii_digits(value):
    m = map_upstream_error(_err(429, headers={"retry-after": value.encode("utf-8")}))
    assert "retry-after" not in m.headers


def test_retry_after_surrounding_whitespace_stripped():
    assert map_upstream_error(_err(429, headers={"retry-after": " 5\n"})).headers == {
        "retry-after": "5"
    }


def test_retry_after_ten_digits_kept():
    assert map_upstream_error(_err(429, headers={"retry-after": "1234567890"})).headers == {
        "retry-after": "1234567890"
    }


@pytest.mark.parametrize(
    "value",
    [b"r\xe2\x82\xac", b"caf\xc3\xa9", b"a\x7fb", b"a\x01b", b"x" * 257],
    ids=["euro", "e-acute", "del", "ctrl", "too-long"],
)
@pytest.mark.parametrize("name", ["x-request-id", "request-id", "x-should-retry"])
def test_unsafe_forwarded_header_values_dropped(name, value):
    assert map_upstream_error(_err(503, headers={name: value})).headers == {}


def test_unsafe_ratelimit_header_dropped_and_boundary_kept():
    ok = "x" * 256
    m = map_upstream_error(
        _err(
            503,
            headers={
                "anthropic-ratelimit-unified-status": b"\xe2\x82\xac",
                "anthropic-ratelimit-unified-reset": ok,
            },
        )
    )
    assert m.headers == {"anthropic-ratelimit-unified-reset": ok}


def test_non_ascii_headers_do_not_break_real_fastapi_response():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    exc = _err(
        429,
        "slow down",
        headers={"retry-after": b"\xd9\xa3", "x-request-id": b"r\xe2\x82\xac", "request-id": "ok1"},
        cls=RateLimitError,
    )
    app = FastAPI()

    @app.get("/boom")
    async def boom():
        raise UpstreamHTTPError(map_upstream_error(exc))

    res = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert res.status_code == 429
    assert res.json() == {"detail": "slow down"}
    assert res.headers["request-id"] == "ok1"
    assert "retry-after" not in res.headers and "x-request-id" not in res.headers


@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
async def test_mapped_errors_do_not_chain_raw_exception(monkeypatch, failures, stream):
    oc = _make_client(monkeypatch, _err(401, "raw secret text", cls=AuthenticationError))
    with pytest.raises(UpstreamError) as ei:
        if stream:
            await _drain(oc.create_chat_completion_stream(dict(REQUEST), None, "big"))
        else:
            await oc.create_chat_completion(dict(REQUEST), None, "big")
    assert ei.value.__cause__ is None
    assert ei.value.__suppress_context__ is True


async def test_log_line_escapes_newlines(monkeypatch, failures, caplog):
    import logging

    oc = _make_client(monkeypatch, _err(400, "line1\nFORGED | ERROR | x\r\nline3"))
    with caplog.at_level(logging.WARNING, logger="client"):
        with pytest.raises(UpstreamError):
            await oc.create_chat_completion(dict(REQUEST), None, "big")
    records = [r for r in caplog.records if r.name == "client"]
    assert len(records) == 1
    text = records[0].getMessage()
    assert "\n" not in text and "\r" not in text
    assert "line1\\nFORGED" in text


def test_redact_keys_pool_and_min_length():
    from src.core.errors import redact_keys

    assert redact_keys("a pool-key-0001 b", ["pool-key-0001"]) == "a [redacted] b"
    assert redact_keys("x abcdefg y", ["abcdefg"]) == "x abcdefg y"  # 7 chars: skipped
    assert redact_keys("x abcdefgh y", ["abcdefgh", None, ""]) == "x [redacted] y"
    m = map_upstream_error(_err(401, "echo other-key-9999"), "fake-key-1234", ["other-key-9999"])
    assert m.message == "echo [redacted]"
    short = map_upstream_error(_err(500, "banana"), "a")
    assert short.message == "banana"


async def test_client_redacts_whole_provider_pool(monkeypatch, failures):
    monkeypatch.setattr(
        client_module.config,
        "providers",
        [{"api_key": "fake-key-1234"}, {"api_key": "pool-key-0002"}, {"api_key": "tiny"}],
    )
    oc = _make_client(monkeypatch, _err(401, "saw pool-key-0002 and tiny", cls=AuthenticationError))
    with pytest.raises(UpstreamHTTPError) as ei:
        await oc.create_chat_completion(dict(REQUEST), None, "big")
    assert ei.value.detail == "saw [redacted] and tiny"


async def test_pool_read_is_defensive(monkeypatch, failures):
    monkeypatch.setattr(client_module.config, "providers", [object()])  # no .get
    oc = _make_client(monkeypatch, _err(401, "bad fake-key-1234", cls=AuthenticationError))
    with pytest.raises(UpstreamHTTPError) as ei:
        await oc.create_chat_completion(dict(REQUEST), None, "big")
    assert ei.value.detail == "bad [redacted]"


async def test_stream_cancel_reports_499_once_and_yields_nothing_more(monkeypatch, failures):
    import asyncio

    calls, _ = failures
    oc = OpenAIClient("fake-key-1234", "https://upstream.invalid/v1")
    reports = []
    monkeypatch.setattr(oc, "_report_model_error", lambda s, d: reports.append((s, d)))

    class Chunk:
        def model_dump(self):
            return {"choices": []}

    async def upstream():
        yield Chunk()
        yield Chunk()
        yield Chunk()

    async def create(**kw):
        return upstream()

    monkeypatch.setattr(oc.client.chat.completions, "create", create)
    gen = oc.create_chat_completion_stream(dict(REQUEST), "rid", "big")
    first = await gen.__anext__()
    assert first.startswith("data: ")
    oc.cancel_request("rid")
    rest = [x async for x in gen]
    assert rest == []
    assert reports == [(499, "Request cancelled")]
    assert oc.active_requests == {}
    assert calls == []


async def test_non_stream_asyncio_cancellation_propagates_and_cleans_up(monkeypatch, failures):
    import asyncio

    calls, _ = failures
    oc = OpenAIClient("fake-key-1234", "https://upstream.invalid/v1")
    started = asyncio.Event()

    async def hang(**kw):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(oc.client.chat.completions, "create", hang)
    task = asyncio.create_task(oc.create_chat_completion(dict(REQUEST), "rid2", "big"))
    await started.wait()
    assert "rid2" in oc.active_requests
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert oc.active_requests == {}
    assert calls == []


async def test_non_stream_cancel_request_gives_499(monkeypatch, failures):
    import asyncio

    oc = OpenAIClient("fake-key-1234", "https://upstream.invalid/v1")
    started = asyncio.Event()

    async def hang(**kw):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(oc.client.chat.completions, "create", hang)
    task = asyncio.create_task(oc.create_chat_completion(dict(REQUEST), "rid3", "big"))
    await started.wait()
    oc.cancel_request("rid3")
    with pytest.raises(HTTPException) as ei:
        await task
    assert ei.value.status_code == 499
    assert not isinstance(ei.value, UpstreamError)
    assert oc.active_requests == {}


def test_mapper_message_is_always_utf8_encodable():
    exc = _err(400, body={"error": {"message": "bad \ud800 and \udfff text"}})
    mapped = map_upstream_error(exc)
    assert mapped.message == "bad \ufffd and \ufffd text"
    error_json(mapped.error_type, mapped.message).encode("utf-8")
    non_api = map_upstream_error(RuntimeError("x \ud800 y"))
    assert non_api.message == "Unexpected error: x \ufffd y"


@pytest.mark.parametrize(
    "exc,expected",
    [
        (ConnectionResetError(), "Unexpected error: ConnectionResetError"),
        (RuntimeError("   "), "Unexpected error: RuntimeError"),
        (RuntimeError("boom"), "Unexpected error: boom"),
    ],
)
def test_empty_text_for_non_http_errors_uses_the_type_name(exc, expected):
    assert map_upstream_error(exc).message == expected
