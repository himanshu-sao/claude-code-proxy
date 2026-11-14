from fastapi.testclient import TestClient

from src.conversion.request_converter import _is_reasoning_model
from src.main import app

client = TestClient(app)


def test_list_models():
    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    assert data["has_more"] is False
    assert isinstance(data["data"], list)
    # Contains the 3 Claude aliases (one per tier) plus configured tier primaries
    assert len(data["data"]) >= 3
    for item in data["data"]:
        assert item["type"] == "model"
        assert item["object"] == "model"
        assert "display_name" in item
        assert "created_at" in item
        # display_name should not contain raw date suffixes like -20241022
        import re

        assert not re.search(r"-\d{8}", item["display_name"])
    model_ids = [m["id"] for m in data["data"]]
    assert "claude-3-5-sonnet-20241022" in model_ids


def test_api_hello_endpoint():
    res_get = client.get("/api/hello")
    assert res_get.status_code == 200
    assert res_get.json() == {"status": "ok"}

    res_head = client.head("/api/hello")
    assert res_head.status_code == 200


def test_is_reasoning_model():
    assert _is_reasoning_model("deepseek-r1") is True
    assert _is_reasoning_model("deepseek/deepseek-r1") is True
    assert _is_reasoning_model("moonshotai/kimi-k3") is True
    assert _is_reasoning_model("o1-mini") is True
    assert _is_reasoning_model("o3-mini") is True

    # Verify non-reasoning models with similar substrings do not falsely match
    assert _is_reasoning_model("gpt-4o") is False
    assert _is_reasoning_model("custom-provider1") is False
    assert _is_reasoning_model("server1") is False
    assert _is_reasoning_model("ver1") is False


# --- Auto model alias (T1) ---------------------------------------------------

import hashlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

from src.api import endpoints  # noqa: E402
from src.core import signal_log  # noqa: E402
from src.core.config import config as _config  # noqa: E402
from src.core.model_manager import model_manager  # noqa: E402


@pytest.fixture(autouse=True)
def signal_path(tmp_path, monkeypatch):
    """Keep every /v1/messages test away from the real logs/ directory.

    src/__init__.py runs load_dotenv(override=True), so a developer .env with
    AUTO_SIGNAL_LOG=1 would otherwise make these tests write to logs/auto_signal.log.
    """
    path = tmp_path / "auto_signal.log"
    monkeypatch.delenv("AUTO_SIGNAL_LOG", raising=False)
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(path))
    # Sentinel client keys must not hit a 401 when a developer .env sets ANTHROPIC_API_KEY.
    monkeypatch.setattr(_config, "anthropic_api_key", None)
    signal_log.reset_for_tests()
    yield path
    signal_log.reset_for_tests()


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
        chunk = {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
        yield "data: " + json.dumps(chunk)
        yield "data: [DONE]"

    def cancel_request(self, request_id):
        pass


@pytest.fixture
def stub_upstream(monkeypatch):
    async def _next_async(*, stream=False):
        return _StubClient()

    monkeypatch.setattr(_config, "get_next_client", lambda: _StubClient())
    monkeypatch.setattr(_config, "get_next_client_async", _next_async)
    calls = []
    monkeypatch.setattr(
        endpoints, "_write_last_model", lambda tier, model: calls.append((tier, model))
    )
    return calls


def _post(model, stream=False):
    return client.post(
        "/v1/messages",
        json={
            "model": model,
            "max_tokens": 100,
            "stream": stream,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )


def _reason_lines(caplog):
    return [r.getMessage() for r in caplog.records if "reason=" in r.getMessage()]


@pytest.fixture
def propagate_logs(caplog):
    # The "proxy" logger propagates to root, where caplog's handler is attached.
    caplog.set_level(logging.INFO)
    return caplog


def test_list_models_includes_auto_alias_last():
    data = client.get("/v1/models").json()["data"]
    last = data[-1]
    assert last["id"] == _config.auto_model_alias
    assert last["type"] == "model"
    assert last["object"] == "model"
    assert last["owned_by"] == "claude-code-proxy"
    assert "created_at" in last and "created" in last
    assert not re.search(r"-\d{8}", last["display_name"])
    assert len(data) == 4


def test_list_models_hides_auto_alias_when_disabled(monkeypatch):
    monkeypatch.setattr(_config, "auto_model_enabled", False)
    data = client.get("/v1/models").json()["data"]
    assert len(data) == 3
    assert _config.auto_model_alias not in [m["id"] for m in data]


def test_auto_alias_request_log_and_last_model(propagate_logs, stub_upstream):
    res = _post("Claude-Proxy-Auto")
    assert res.status_code == 200
    lines = _reason_lines(propagate_logs)
    assert len(lines) == 1
    assert "reason=auto-placeholder" in lines[0]
    assert "tier=big" in lines[0]
    assert stub_upstream == [("big", _config.get_active_model("big"))]


def test_auto_alias_response_echoes_requested_model_non_streaming(stub_upstream):
    res = _post("Claude-Proxy-Auto")
    assert res.json()["model"] == "Claude-Proxy-Auto"


def test_auto_alias_response_echoes_requested_model_streaming(stub_upstream):
    res = _post("Claude-Proxy-Auto", stream=True)
    assert res.status_code == 200
    start = None
    for line in res.text.splitlines():
        if line.startswith("data: ") and '"message_start"' in line:
            start = json.loads(line[6:])
            break
    assert start is not None
    assert start["message"]["model"] == "Claude-Proxy-Auto"
    assert stub_upstream == [("big", _config.get_active_model("big"))]


def test_tier_map_request_logs_tier_map_reason(propagate_logs, stub_upstream):
    res = _post("claude-3-opus-20240229")
    assert res.status_code == 200
    lines = _reason_lines(propagate_logs)
    assert len(lines) == 1
    assert "reason=tier-map" in lines[0]


def test_disabled_alias_logs_tier_map(propagate_logs, stub_upstream, monkeypatch):
    monkeypatch.setattr(_config, "auto_model_enabled", False)
    _post("claude-proxy-auto")
    lines = _reason_lines(propagate_logs)
    assert len(lines) == 1
    assert "reason=tier-map" in lines[0]


# --- Signal log wiring (T5) ----------------------------------------------------

ALIAS = "claude-proxy-auto"
TIER_MODEL = "claude-3-opus-20240229"


def _signal_records(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            assert "AUTOSIGNAL " in line
            out.append(json.loads(line.split("AUTOSIGNAL ", 1)[1]))
    return out


def _event_types(res):
    return [ln[len("event: ") :] for ln in res.text.splitlines() if ln.startswith("event: ")]


def _outcome(res, stream):
    """Status plus either the body without its generated id or the ordered SSE event types."""
    if stream:
        return (res.status_code, _event_types(res))
    body = dict(res.json())
    body.pop("id", None)
    return (res.status_code, body)


def _skipped_records(caplog):
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "proxy" and r.getMessage().startswith("signal log skipped")
    ]


@pytest.fixture
def debug_logs(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
@pytest.mark.parametrize("model,is_auto", [(ALIAS, True), (TIER_MODEL, False)])
def test_signal_log_one_line_per_request(
    stub_upstream, signal_path, monkeypatch, model, is_auto, stream
):
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    res = _post(model, stream=stream)
    assert res.status_code == 200
    records = _signal_records(signal_path)
    assert len(records) == 1
    assert records[0]["auto"] is is_auto
    assert records[0]["stream"] is stream
    assert records[0]["model"] == model
    # A second request appends exactly one more line.
    _post(model, stream=stream)
    assert len(_signal_records(signal_path)) == 2


def test_signal_log_failed_upstream_is_still_logged_once(stub_upstream, signal_path, monkeypatch):
    async def _boom(self, request, request_id=None, model_tier=None):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(_StubClient, "create_chat_completion", _boom)
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    res = _post(ALIAS)
    assert res.status_code == 500
    assert res.json() == {
        "type": "error",
        "error": {"type": "api_error", "message": "Internal server error"},
    }
    assert len(_signal_records(signal_path)) == 1


@pytest.fixture
def emit_spy(monkeypatch):
    calls = []
    real = signal_log.emit_signal

    def _spy(request, headers, is_auto_alias):
        calls.append(is_auto_alias)
        return real(request, headers, is_auto_alias)

    monkeypatch.setattr(signal_log, "emit_signal", _spy)
    return calls


@pytest.mark.parametrize(
    "bad_body",
    [
        {
            "model": ALIAS,
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "x"}],
            "reasoning_effort": "bogus",
        },
        {"model": ALIAS, "max_tokens": 10},
    ],
    ids=["invalid-reasoning-effort", "missing-messages"],
)
def test_signal_log_422_is_not_logged(stub_upstream, signal_path, monkeypatch, emit_spy, bad_body):
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    res = client.post("/v1/messages", json=bad_body)
    assert res.status_code == 422
    assert emit_spy == []
    assert not signal_path.exists()
    # The same fixture with a valid body logs one line.
    assert _post(ALIAS).status_code == 200
    assert len(emit_spy) == 1
    assert len(_signal_records(signal_path)) == 1


@pytest.mark.parametrize("value", [None, "0"], ids=["unset", "zero"])
@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
def test_signal_log_off_creates_nothing(stub_upstream, signal_path, monkeypatch, value, stream):
    if value is not None:
        monkeypatch.setenv("AUTO_SIGNAL_LOG", value)
    res = _post(ALIAS, stream=stream)
    assert res.status_code == 200
    assert not signal_path.exists()
    assert list(signal_path.parent.iterdir()) == []
    assert logging.getLogger("auto_signal").handlers == []


def test_signal_log_header_privacy(stub_upstream, signal_path, monkeypatch):
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    sentinels = {
        "x-api-key": "SENTINEL-APIKEY-7f3a",
        "authorization": "Bearer SENTINEL-BEARER-91bc",
        "x-claude-code-session-id": "SENTINEL-SESSION-55de",
        "anthropic-beta": "SENTINEL-BETA-20ff",
    }
    res = client.post(
        "/v1/messages",
        headers=sentinels,
        json={
            "model": ALIAS,
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "SENTINEL-USERTEXT-c0de"}],
        },
    )
    assert res.status_code == 200
    raw = signal_path.read_text(encoding="utf-8")
    records = _signal_records(signal_path)
    assert len(records) == 1
    rec = records[0]
    for name in sentinels:
        assert name in rec["header_names"]
    assert rec["beta"] is True
    assert rec["sid"] is True
    expected = hashlib.sha256(
        ("sid:" + sentinels["x-claude-code-session-id"]).encode("utf-8")
    ).hexdigest()[:8]
    assert rec["sid_hash"] == expected
    for value in list(sentinels.values()) + ["SENTINEL-USERTEXT-c0de", "SENTINEL-"]:
        assert value not in raw
    assert "Bearer" not in raw


def _boom_emit(request, headers, is_auto_alias):
    raise RuntimeError("x")


def _setup_failure(case, monkeypatch, tmp_path):
    """Install one failing-log scenario; return the spy list for emit_signal (or None)."""
    if case == "unwritable-path":
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        monkeypatch.setattr(signal_log, "_log_path", lambda: str(blocker / "auto_signal.log"))
        return None
    if case == "emit-raises":
        monkeypatch.setattr(signal_log, "emit_signal", _boom_emit)
        return None
    # "args-raise": fail only while the call-site arguments are evaluated inside the helper.
    # is_auto_alias is also used by map_claude_model_to_openai and by T1's reason= expression,
    # so the wrapper delegates to the real method for every other caller.
    real = model_manager.is_auto_alias

    def _wrapper(name):
        if sys._getframe(1).f_code.co_name == "_emit_signal_safe":
            raise RuntimeError("x")
        return real(name)

    monkeypatch.setattr(model_manager, "is_auto_alias", _wrapper)
    calls = []
    monkeypatch.setattr(signal_log, "emit_signal", lambda *a, **k: calls.append(a))
    return calls


@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
@pytest.mark.parametrize("case", ["unwritable-path", "emit-raises", "args-raise"])
def test_signal_log_failure_leaves_response_unchanged(
    stub_upstream, signal_path, monkeypatch, debug_logs, tmp_path, case, stream
):
    baseline = _outcome(_post(ALIAS, stream=stream), stream)
    assert baseline[0] == 200
    assert not signal_path.exists()
    debug_logs.clear()
    del stub_upstream[:]

    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    spy = _setup_failure(case, monkeypatch, tmp_path)
    res = _post(ALIAS, stream=stream)

    assert _outcome(res, stream) == baseline
    assert stub_upstream == [("big", _config.get_active_model("big"))]
    reasons = _reason_lines(debug_logs)
    assert len(reasons) == 1 and "reason=auto-placeholder" in reasons[0]
    assert not signal_path.exists()
    skipped = _skipped_records(debug_logs)
    if case == "unwritable-path":
        # emit_signal swallows this itself: the helper's guard is not reached.
        assert skipped == []
        assert any("signal_log: emit failed" in r.getMessage() for r in debug_logs.records)
    else:
        assert skipped == ["signal log skipped: RuntimeError"]
    if spy is not None:
        assert spy == []


@pytest.mark.parametrize("model", [ALIAS, TIER_MODEL])
def test_reason_line_once_with_signal_log_on(propagate_logs, stub_upstream, monkeypatch, model):
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    assert _post(model).status_code == 200
    lines = _reason_lines(propagate_logs)
    assert len(lines) == 1
    assert ("reason=auto-placeholder" if model == ALIAS else "reason=tier-map") in lines[0]


@pytest.mark.parametrize("log_on", [False, True], ids=["log-off", "log-on"])
@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
def test_signal_log_does_not_change_echo_or_routing(
    stub_upstream, signal_path, monkeypatch, log_on, stream
):
    if log_on:
        monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    res = _post("Claude-Proxy-Auto", stream=stream)
    assert res.status_code == 200
    if stream:
        start = None
        for line in res.text.splitlines():
            if line.startswith("data: ") and '"message_start"' in line:
                start = json.loads(line[6:])
                break
        assert start is not None
        assert start["message"]["model"] == "Claude-Proxy-Auto"
    else:
        assert res.json()["model"] == "Claude-Proxy-Auto"
    assert stub_upstream == [("big", _config.get_active_model("big"))]
    assert signal_path.exists() is log_on
