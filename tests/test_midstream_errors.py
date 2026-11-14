"""Mid-stream error contract for the streaming converter (offline, drives it directly)."""

import asyncio
import json
import logging
import uuid

import httpx
import pytest
from fastapi import HTTPException
from openai import APIStatusError

from src.conversion.response_converter import (
    convert_openai_streaming_to_claude_with_cancellation as convert,
)
from src.core.errors import UpstreamError, UpstreamHTTPError, map_upstream_error
from src.models.claude import ClaudeMessagesRequest

REQ = httpx.Request("POST", "https://upstream.invalid/v1/chat/completions")
FIXED_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")


class _Http:
    async def is_disconnected(self):
        return False


class _Client:
    def cancel_request(self, request_id):
        pass


def _chunk(delta=None, finish=None, usage=None):
    if delta is None and finish is None:
        data = {"choices": []}
    else:
        data = {"choices": [{"delta": delta or {}, "finish_reason": finish}]}
    if usage:
        data["usage"] = usage
    return "data: " + json.dumps(data)


def _text(s):
    return _chunk({"content": s})


def _upstream_error(status, message="upstream said no"):
    resp = httpx.Response(status, request=REQ)
    exc = APIStatusError(message, response=resp, body={"error": {"message": message}})
    return UpstreamError(map_upstream_error(exc))


def _run(lines, raises=None):
    """Run the converter over `lines`, then raise `raises` (if any). Returns the joined output."""

    async def stream():
        for line in lines:
            yield line
        if raises is not None:
            raise raises

    async def go():
        req = ClaudeMessagesRequest(
            model="claude-sonnet-4", max_tokens=10, messages=[{"role": "user", "content": "hi"}]
        )
        out = []
        async for ev in convert(
            stream(), req, logging.getLogger("test"), _Http(), _Client(), "rid"
        ):
            out.append(ev)
        return "".join(out)

    return asyncio.run(go())


def _events(output):
    return [ln[len("event: ") :] for ln in output.split("\n") if ln.startswith("event: ")]


def _error_data(output):
    block = output.split("event: error\ndata: ", 1)[1]
    assert block.endswith("\n\n")
    return json.loads(block[:-2])


@pytest.mark.parametrize("status", [503, 429, 400])
def test_midstream_upstream_error_is_last_event(status):
    err = _upstream_error(status)
    out = _run([_text("hi")], raises=err)
    assert out.endswith("\n\n")
    assert _events(out).count("error") == 1
    assert _events(out)[-1] == "error"
    assert "message_stop" not in out
    assert "message_delta" not in out
    assert _error_data(out) == {
        "type": "error",
        "error": {"type": err.mapped.error_type, "message": err.mapped.message},
    }


def test_midstream_generic_exception_is_sanitised():
    out = _run([_text("hi")], raises=RuntimeError("secret " + "key-abc"))
    assert _error_data(out) == {
        "type": "error",
        "error": {"type": "api_error", "message": "Streaming error: RuntimeError"},
    }
    assert "secret" not in out
    assert "message_stop" not in out


def test_midstream_499_still_cancelled_event():
    out = _run([_text("hi")], raises=HTTPException(status_code=499, detail="x"))
    assert _error_data(out)["error"] == {
        "type": "cancelled",
        "message": "Request was cancelled by client",
    }
    assert _events(out)[-1] == "error"
    assert _events(out).count("error") == 1
    assert "message_stop" not in out


def test_midstream_upstream_http_error_uses_upstream_handler():
    """UpstreamHTTPError is both an UpstreamError and an HTTPException; the UpstreamError
    handler must win, so the mapped type is emitted instead of re-raising."""
    resp = httpx.Response(503, request=REQ)
    exc = APIStatusError("down", response=resp, body={"error": {"message": "down"}})
    err = UpstreamHTTPError(map_upstream_error(exc))
    out = _run([_text("hi")], raises=err)
    assert _events(out)[-1] == "error"
    assert _events(out).count("error") == 1
    assert "message_stop" not in out
    assert _error_data(out) == {
        "type": "error",
        "error": {"type": err.mapped.error_type, "message": err.mapped.message},
    }


def test_midstream_hostile_upstream_text_creates_one_event():
    hostile = 'x"\r\n\nevent: message_stop\ndata: {}'
    err = _upstream_error(503, hostile)
    out = _run([_text("hi")], raises=err)
    assert err.mapped.message == hostile
    assert [ln for ln in out.split("\n") if ln.startswith("event: error")] == ["event: error"]
    assert "event: message_stop" not in out.split("\n")
    assert _events(out).count("error") == 1
    assert _error_data(out)["error"]["message"] == hostile


def test_midstream_error_after_tool_call_started_ends_with_error_only():
    """Edge case 6 (decision): the error event is terminal. After it we emit NOTHING: no
    content_block_stop for the open text block or the half-streamed tool_use block, no
    message_delta and no message_stop. Closing the tool block would present truncated tool
    input as a complete block; Anthropic's documented error signal is `event: error`."""
    lines = [
        _text("hi"),
        _chunk({"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "f"}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"a": '}}]}),
    ]
    out = _run(lines, raises=_upstream_error(503))
    events = _events(out)
    assert '"index": 1, "content_block": {"type": "tool_use"' in out
    assert events[-1] == "error"
    tail = out.split("event: error", 1)[1]
    assert tail.count("event:") == 0
    for forbidden in ("content_block_stop", "message_delta", "message_stop"):
        assert forbidden not in events


def test_done_without_finish_reason_ends_cleanly():
    """Edge case 7: [DONE] with no finish_reason closes normally with end_turn, no error."""
    out = _run([_text("hi"), "data: [DONE]"])
    events = _events(out)
    assert events[-3:] == ["content_block_stop", "message_delta", "message_stop"]
    assert "error" not in events
    assert '"stop_reason": "end_turn"' in out


def test_stream_ending_without_done_ends_cleanly():
    out = _run([_text("hi")])
    assert _events(out)[-3:] == ["content_block_stop", "message_delta", "message_stop"]
    assert "error" not in _events(out)


BASELINE_SUCCESS_OUTPUT = 'event: message_start\ndata: {"type": "message_start", "message": {"id": "msg_123456781234567812345678", "type": "message", "role": "assistant", "model": "claude-sonnet-4", "content": [], "stop_reason": null, "stop_sequence": null, "usage": {"input_tokens": 0, "output_tokens": 0}}}\n\nevent: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}\n\nevent: ping\ndata: {"type": "ping"}\n\nevent: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": ""}}\n\nevent: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}\n\nevent: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " wörld"}}\n\nevent: content_block_start\ndata: {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {}}}\n\nevent: content_block_delta\ndata: {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\\"city\\": \\"Paris\\"}"}}\n\nevent: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\nevent: content_block_stop\ndata: {"type": "content_block_stop", "index": 1}\n\nevent: message_delta\ndata: {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": null}, "usage": {"input_tokens": 11, "output_tokens": 7, "cache_read_input_tokens": 5}}\n\nevent: message_stop\ndata: {"type": "message_stop"}\n\n'


def test_success_path_is_byte_identical_to_baseline(monkeypatch):
    """Expected bytes were captured from the unmodified converter at commit 6c82d50."""
    monkeypatch.setattr(uuid, "uuid4", lambda: FIXED_UUID)
    lines = [
        _chunk({"role": "assistant", "content": ""}),
        _text("Hello"),
        "",
        _text(" w\u00f6rld"),
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "get_weather", "arguments": ""},
                    }
                ]
            }
        ),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"city": '}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"Paris"}'}}]}),
        _chunk({}, "tool_calls"),
        _chunk(
            None,
            None,
            {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 5},
            },
        ),
        "data: [DONE]",
    ]
    assert _run(lines) == BASELINE_SUCCESS_OUTPUT
