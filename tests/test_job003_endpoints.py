"""Job-003 endpoint tests (TestClient plus stubs only; no network, no ports).

Covers: 422 for reasoning_effort values outside the case-sensitive Literal (no upstream call),
the reason= request-log line on the streaming path, /v1/models shape, the API-key boundary
for the messages, compat and public routes, and upstream error pass-through (status, detail,
which errors count as model failures).
"""

import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIStatusError, BadRequestError, RateLimitError

from src.api import compat, endpoints
from src.core.client import OpenAIClient
from src.core.config import Config
from src.core.config import config as _config
from src.core.errors import error_type_for_status
from src.main import app

client = TestClient(app)

ALIAS = "claude-proxy-auto"
TIER_MODEL = "claude-3-opus-20240229"
KEY = "test-secret-key"
COUNT_TOKENS_BODY = {"model": ALIAS, "messages": [{"role": "user", "content": "hi"}]}


@pytest.fixture(autouse=True)
def _no_client_key(monkeypatch):
    # Developer .env may set ANTHROPIC_API_KEY; the non-auth tests must not depend on it.
    monkeypatch.setattr(_config, "anthropic_api_key", None)


def _body(model=ALIAS, stream=False, **extra):
    body = {
        "model": model,
        "max_tokens": 100,
        "stream": stream,
        "messages": [{"role": "user", "content": "hello"}],
    }
    body.update(extra)
    return body


class _StubClient:
    async def create_chat_completion(self, request, request_id=None, model_tier=None):
        return {
            "id": "chatcmpl-test",
            "choices": [
                {"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    async def create_chat_completion_stream(self, request, request_id=None, model_tier=None):
        yield 'data: {"choices": [{"delta": {"content": "hi"}, "finish_reason": null}]}'
        yield "data: [DONE]"

    def cancel_request(self, request_id):
        pass


@pytest.fixture
def upstream(monkeypatch):
    """Stub both client accessors; return the list of upstream acquisitions (empty = no call)."""
    calls = []

    async def _next_async(*, stream=False):
        calls.append("async")
        return _StubClient()

    def _next_sync():
        calls.append("sync")
        return _StubClient()

    monkeypatch.setattr(_config, "get_next_client", _next_sync)
    monkeypatch.setattr(_config, "get_next_client_async", _next_async)
    monkeypatch.setattr(endpoints, "_write_last_model", lambda tier, model: None)
    return calls


@pytest.fixture
def propagate_logs(caplog):
    caplog.set_level(logging.INFO)
    return caplog


def _reason_lines(caplog):
    return [r.getMessage() for r in caplog.records if "reason=" in r.getMessage()]


def _with_config(monkeypatch, **env):
    """Swap the endpoints module's config for a fresh Config built from the given env."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for var in ("AUTO_MODEL_ALIAS", "AUTO_MODEL_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    cfg = Config()
    monkeypatch.setattr(endpoints, "config", cfg)
    return cfg


# --- (1) effort values at the HTTP boundary -------------------------------------------------


@pytest.mark.parametrize("effort", ["bogus", "HIGH", "Max", "", "xHigh"])
@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
def test_top_level_effort_outside_literal_is_422_without_upstream(
    upstream, monkeypatch, effort, stream
):
    converted = []
    monkeypatch.setattr(endpoints, "convert_claude_to_openai", lambda *a, **k: converted.append(a))
    res = client.post("/v1/messages", json=_body(stream=stream, reasoning_effort=effort))
    assert res.status_code == 422
    assert any("reasoning_effort" in str(item.get("loc")) for item in res.json()["detail"])
    assert upstream == []
    assert converted == []


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
def test_valid_top_level_effort_reaches_converter(upstream, monkeypatch, effort, stream):
    seen = []
    real = endpoints.convert_claude_to_openai

    def spy(request, manager):
        seen.append(request.reasoning_effort)
        return real(request, manager)

    monkeypatch.setattr(endpoints, "convert_claude_to_openai", spy)
    res = client.post("/v1/messages", json=_body(stream=stream, reasoning_effort=effort))
    assert res.status_code == 200
    assert seen == [effort]
    assert len(upstream) == 1


def test_top_level_max_is_forwarded_as_max_to_upstream(upstream, monkeypatch):
    # GLM speaks low|high|max, so a canonical "max" must reach the upstream body unchanged.
    captured = []

    class _Capture(_StubClient):
        async def create_chat_completion(self, request, request_id=None, model_tier=None):
            captured.append(request)
            return await super().create_chat_completion(request, request_id, model_tier)

    monkeypatch.setattr(_config, "big_models", ["z-ai/glm-5.1"])

    async def _capture_async(*, stream=False):
        return _Capture()

    monkeypatch.setattr(_config, "get_next_client", lambda: _Capture())
    # Request handlers use the async getter (the sync one sleeps on the event loop).
    monkeypatch.setattr(_config, "get_next_client_async", _capture_async)
    res = client.post("/v1/messages", json=_body(model=TIER_MODEL, reasoning_effort="max"))
    assert res.status_code == 200
    assert len(captured) == 1
    assert captured[0]["model"] == "z-ai/glm-5.1"
    assert captured[0]["reasoning_effort"] == "max"


def test_malformed_output_config_never_422s(upstream, monkeypatch):
    seen = []
    real = endpoints.convert_claude_to_openai

    def spy(request, manager):
        seen.append(request.output_config)
        return real(request, manager)

    monkeypatch.setattr(endpoints, "convert_claude_to_openai", spy)
    res = client.post("/v1/messages", json=_body(output_config={"effort": "HIGH"}))
    assert res.status_code == 200
    assert seen == [{"effort": "HIGH"}]


# --- (3) reason= on the streaming path ------------------------------------------------------


@pytest.mark.parametrize("signal_on", [False, True], ids=["signal-off", "signal-on"])
@pytest.mark.parametrize(
    "model,reason",
    [(ALIAS, "reason=auto-placeholder"), (TIER_MODEL, "reason=tier-map")],
    ids=["alias", "tier-map"],
)
def test_reason_logged_exactly_once_when_streaming(
    propagate_logs, upstream, monkeypatch, model, reason, signal_on
):
    if signal_on:
        monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    res = client.post("/v1/messages", json=_body(model=model, stream=True))
    assert res.status_code == 200
    lines = _reason_lines(propagate_logs)
    assert len(lines) == 1
    assert reason in lines[0]
    assert "stream=True" in lines[0]


# --- (5) /v1/models -------------------------------------------------------------------------

_TIER_IDS = ["claude-3-opus-20240229", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]


def test_models_default_has_four_entries_alias_last(monkeypatch):
    _with_config(monkeypatch)
    body = client.get("/v1/models").json()
    ids = [m["id"] for m in body["data"]]
    assert ids == _TIER_IDS + [ALIAS]
    assert body["first_id"] == _TIER_IDS[0]
    assert body["last_id"] == ALIAS


def test_models_auto_entry_has_usual_fields_and_display_name(monkeypatch):
    _with_config(monkeypatch)
    entry = client.get("/v1/models").json()["data"][-1]
    assert entry["display_name"] == "Auto (routes to big tier)"
    assert entry["type"] == "model"
    assert entry["object"] == "model"
    assert entry["owned_by"] == "claude-code-proxy"
    assert entry["created_at"] == "2025-01-01T00:00:00Z"
    assert entry["created"] == 1735689600
    assert set(entry) == {
        "id",
        "type",
        "object",
        "display_name",
        "created_at",
        "created",
        "owned_by",
    }


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_models_disabled_has_three_entries(monkeypatch, value):
    _with_config(monkeypatch, AUTO_MODEL_ENABLED=value)
    body = client.get("/v1/models").json()
    assert [m["id"] for m in body["data"]] == _TIER_IDS
    assert body["last_id"] == _TIER_IDS[-1]


def test_models_custom_alias_keeps_casing_and_is_stripped(monkeypatch):
    _with_config(monkeypatch, AUTO_MODEL_ALIAS="  My-Auto-Model  ")
    body = client.get("/v1/models").json()
    assert body["data"][-1]["id"] == "My-Auto-Model"
    assert body["last_id"] == "My-Auto-Model"


# --- (6) API-key boundary -------------------------------------------------------------------


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(_config, "anthropic_api_key", KEY)


_BAD_AUTH = [
    pytest.param({}, id="no-key"),
    pytest.param({"x-api-key": "wrong"}, id="wrong-x-api-key"),
    pytest.param({"authorization": "Bearer wrong"}, id="wrong-bearer"),
    pytest.param({"authorization": f"Basic {KEY}"}, id="basic-scheme"),
    pytest.param({"x-api-key": ""}, id="empty-x-api-key"),
]


@pytest.mark.parametrize("headers", _BAD_AUTH)
def test_messages_rejects_wrong_or_missing_key(keyed, upstream, headers):
    res = client.post("/v1/messages", json=_body(), headers=headers)
    assert res.status_code == 401
    assert upstream == []


@pytest.mark.parametrize("headers", _BAD_AUTH)
def test_count_tokens_rejects_wrong_or_missing_key(keyed, headers):
    res = client.post("/v1/messages/count_tokens", json=COUNT_TOKENS_BODY, headers=headers)
    assert res.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [{"x-api-key": KEY}, {"authorization": f"Bearer {KEY}"}],
    ids=["x-api-key", "bearer"],
)
def test_correct_key_accepted_on_messages_and_count_tokens(keyed, upstream, headers):
    assert client.post("/v1/messages", json=_body(), headers=headers).status_code == 200
    res = client.post("/v1/messages/count_tokens", json=COUNT_TOKENS_BODY, headers=headers)
    assert res.status_code == 200
    assert res.json()["input_tokens"] >= 1


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("get", "/health", {}),
        ("get", "/v1/models", {}),
        ("get", "/test-connection", {}),
        ("get", "/", {}),
        ("get", "/hello", {}),
        ("get", "/api/hello", {}),
    ],
)
def test_public_routes_need_no_key(keyed, upstream, method, path, kwargs):
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 200


_COMPAT_COVERED_BY_EXISTING_TESTS = {
    ("GET", "/api/organizations"),
    ("GET", "/v1/me"),
    ("POST", "/v1/oauth/token"),
    ("GET", "/v1/mcp_servers"),
    ("GET", "/api/connectors"),
    ("GET", "/api/plugins"),
}
_CATCH_ALL = "/{full_path:path}"


def _compat_routes():
    """(method, concrete path) for every non-catch-all compat route, read from the router."""
    out = []
    for route in compat.router.routes:
        if route.path == _CATCH_ALL:
            continue
        concrete = route.path.replace("{org_id}", compat.ORG_ID).replace(
            "{resource_path:path}", "plugins"
        )
        for method in sorted(route.methods):
            out.append((method, concrete))
    return out


def test_every_compat_route_depends_on_compat_auth():
    # Structural guard: a new compat route added without the auth dependency fails here.
    for route in compat.router.routes:
        if route.path == _CATCH_ALL:
            continue
        deps = [d.call for d in route.dependant.dependencies]
        assert compat._compat_auth in deps, route.path


_COMPAT_NEW = [
    pytest.param(m, p, id="%s %s" % (m, p))
    for m, p in _compat_routes()
    if (m, p) not in _COMPAT_COVERED_BY_EXISTING_TESTS
]


@pytest.mark.parametrize("method,path", _COMPAT_NEW)
def test_compat_routes_reject_wrong_key(keyed, method, path):
    kwargs = {"json": {}} if method == "POST" else {}
    res = client.request(method, path, headers={"x-api-key": "wrong-key"}, **kwargs)
    assert res.status_code == 401


@pytest.mark.parametrize("method,path", _compat_routes())
def test_compat_routes_open_when_no_key_configured(method, path):
    kwargs = {"json": {}} if method == "POST" else {}
    res = client.request(method, path, **kwargs)
    assert res.status_code == 200


# --- (8) upstream error pass-through --------------------------------------------------------


def _api_error(cls, status, message):
    request = httpx.Request("POST", "https://upstream.invalid/v1/chat/completions")
    return cls(message, response=httpx.Response(status, request=request), body=None)


@pytest.fixture
def failing_upstream(monkeypatch):
    """Route /v1/messages through a real OpenAIClient whose upstream call is patched to raise.

    Returns (model_failures, rate_limits, client) so tests can assert the reporting side.
    """
    failures, rate_limits = [], []
    monkeypatch.setattr(_config, "report_model_failure", lambda m, t: failures.append((m, t)))
    monkeypatch.setattr(_config, "report_rate_limit", lambda k: rate_limits.append(k))
    oc = OpenAIClient("upstream-key", "https://upstream.invalid/v1")

    def _install(exc):
        async def _raise(**kwargs):
            raise exc

        monkeypatch.setattr(oc.client.chat.completions, "create", _raise)

    async def _next_async(*, stream=False):
        return oc

    monkeypatch.setattr(_config, "get_next_client", lambda: oc)
    monkeypatch.setattr(_config, "get_next_client_async", _next_async)
    monkeypatch.setattr(endpoints, "_write_last_model", lambda tier, model: None)
    return _install, failures, rate_limits, oc


_PASS_THROUGH = [
    pytest.param(BadRequestError, 400, "bad request body from upstream", False, id="400"),
    pytest.param(APIStatusError, 422, "unprocessable entity from upstream", False, id="422"),
    pytest.param(APIStatusError, 503, "upstream down for maintenance", True, id="503"),
    pytest.param(RateLimitError, 429, "slow down", True, id="429"),
]


@pytest.mark.parametrize("cls,status,message,counts", _PASS_THROUGH)
def test_non_stream_upstream_status_and_text_pass_through(
    failing_upstream, cls, status, message, counts
):
    install, failures, rate_limits, _ = failing_upstream
    install(_api_error(cls, status, message))
    res = client.post("/v1/messages", json=_body(model=TIER_MODEL))
    assert res.status_code == status
    body = res.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == error_type_for_status(status)
    assert body["error"]["message"] == message
    expected = [(_config.get_active_model("big"), "big")] if counts else []
    assert failures == expected
    assert rate_limits == ([] if status != 429 else [failing_upstream[3].api_key])


@pytest.mark.parametrize("cls,status,message,counts", _PASS_THROUGH)
def test_stream_upstream_error_counts_as_model_failure_only_for_503_and_429(
    failing_upstream, cls, status, message, counts
):
    install, failures, _, _ = failing_upstream
    install(_api_error(cls, status, message))
    res = client.post("/v1/messages", json=_body(model=TIER_MODEL, stream=True))
    assert res.status_code == status
    expected = [(_config.get_active_model("big"), "big")] if counts else []
    assert failures == expected


@pytest.mark.parametrize("cls,status,message,counts", _PASS_THROUGH)
def test_stream_upstream_error_is_visible_to_client(failing_upstream, cls, status, message, counts):
    install, _, _, _ = failing_upstream
    install(_api_error(cls, status, message))
    res = client.post("/v1/messages", json=_body(model=TIER_MODEL, stream=True))
    assert res.status_code != 200 or message in res.text


@pytest.mark.parametrize(
    "model,expected_tier",
    [
        (ALIAS, "big"),
        (TIER_MODEL, "big"),
        ("claude-3-5-sonnet-20241022", "middle"),
        ("claude-3-5-haiku-20241022", None),  # small tier never refreshes the statusline
    ],
    ids=["alias-big", "opus-big", "sonnet-middle", "haiku-small-skipped"],
)
def test_last_model_written_except_for_small_tier(upstream, monkeypatch, model, expected_tier):
    writes = []
    monkeypatch.setattr(endpoints, "_write_last_model", lambda tier, name: writes.append(tier))
    assert client.post("/v1/messages", json=_body(model=model)).status_code == 200
    assert writes == ([] if expected_tier is None else [expected_tier])
