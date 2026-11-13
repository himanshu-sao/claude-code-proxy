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

import json  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402

import pytest  # noqa: E402

from src.api import endpoints  # noqa: E402
from src.core.config import config as _config  # noqa: E402


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
    async def _next_async():
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
