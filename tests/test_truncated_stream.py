"""Truncated streams and surrogate-safe errors (sub-job 005-error-contract-e), offline.

A stream whose iterator ends without any choice carrying a finish_reason was cut off: it is an
error, not a normal finish. The SDK strips a real ``data: [DONE]`` line, so an upstream that sends
``[DONE]`` but never a finish_reason cannot be told apart from a clean close at this layer; both
are treated as truncated.
"""

import json

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletionChunk

from src.api import endpoints
from src.core.client import OpenAIClient
from src.core.config import config as _config
from src.core.errors import TRUNCATED_STREAM_MESSAGE, UpstreamError
from src.main import app

client = TestClient(app)
TIER_MODEL = "claude-3-opus-20240229"
_REQ = httpx.Request("POST", "https://upstream.invalid/v1/chat/completions")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(_config, "anthropic_api_key", None)
    monkeypatch.setattr(endpoints, "_write_last_model", lambda tier, model: None)


def _chunk(content=None, finish=None, usage=None, choices=True, extra_choice_finish=None):
    data = {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [],
    }
    if choices:
        data["choices"] = [
            {"index": 0, "delta": {"content": content} if content else {}, "finish_reason": finish}
        ]
        if extra_choice_finish:
            data["choices"].append({"index": 1, "delta": {}, "finish_reason": extra_choice_finish})
    if usage:
        data["usage"] = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    return ChatCompletionChunk.model_validate(data)


class _Stream:
    """Stand-in for the SDK's AsyncStream: yields chunks, then optionally raises."""

    def __init__(self, chunks, raises=None):
        self._chunks, self._raises = list(chunks), raises

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for c in self._chunks:
            yield c
        if self._raises is not None:
            raise self._raises


@pytest.fixture
def upstream(monkeypatch):
    """Install a real OpenAIClient whose SDK create() returns a scripted stream."""
    ledger = {"success": 0, "model_errors": [], "failures": []}
    monkeypatch.setattr(_config, "report_model_failure", lambda m, t: ledger["failures"].append(t))
    monkeypatch.setattr(
        _config,
        "report_model_success",
        lambda m, t: ledger.__setitem__("success", ledger["success"] + 1),
    )

    def _install(chunks, raises=None):
        oc = OpenAIClient("upstream-key", "https://upstream.invalid/v1")

        async def _create(**kwargs):
            return _Stream(chunks, raises)

        monkeypatch.setattr(oc.client.chat.completions, "create", _create)
        orig = oc._report_model_error
        monkeypatch.setattr(
            oc,
            "_report_model_error",
            lambda status, detail: (
                ledger["model_errors"].append((status, detail)),
                orig(status, detail),
            )[1],
        )

        async def _next(*, stream=False):
            return oc

        monkeypatch.setattr(_config, "get_next_client_async", _next)
        return oc

    _install.ledger = ledger
    return _install


async def _collect(oc):
    lines, error = [], None
    try:
        async for line in oc.create_chat_completion_stream(
            {"model": "m", "messages": []}, "rid", "big"
        ):
            lines.append(line)
    except UpstreamError as e:
        error = e
    return lines, error


def _post(stream=True):
    return client.post(
        "/v1/messages",
        json={
            "model": TIER_MODEL,
            "max_tokens": 100,
            "stream": stream,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )


def _events(text):
    return [ln[len("event: ") :] for ln in text.split("\n") if ln.startswith("event: ")]


# --- client layer ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chunks",
    [
        [],
        [_chunk("hi")],
        [_chunk("hi"), _chunk(choices=False, usage=True)],
        [_chunk("hi", finish=None, extra_choice_finish=None), _chunk()],
    ],
    ids=["zero-chunks", "text-then-close", "usage-only-is-not-a-finish", "empty-delta-no-finish"],
)
async def test_stream_without_finish_reason_raises_502_and_no_done(upstream, chunks):
    oc = upstream(chunks)
    lines, error = await _collect(oc)
    assert error is not None
    assert "data: [DONE]" not in lines
    m = error.mapped
    assert (m.status, m.error_type, m.message) == (502, "api_error", TRUNCATED_STREAM_MESSAGE)
    assert m.retryable is True and m.counts_as_model_failure is False
    assert upstream.ledger["success"] == 0
    assert upstream.ledger["failures"] == []
    assert len(upstream.ledger["model_errors"]) == 1
    assert oc.active_requests == {}


@pytest.mark.parametrize("finish", ["stop", "tool_calls", "length"])
@pytest.mark.parametrize("trailing_usage", [False, True], ids=["no-usage", "usage"])
async def test_normal_finish_is_unchanged(upstream, finish, trailing_usage):
    chunks = [_chunk("hi"), _chunk(finish=finish)]
    if trailing_usage:
        chunks.append(_chunk(choices=False, usage=True))
    oc = upstream(chunks)
    lines, error = await _collect(oc)
    assert error is None
    assert lines[-1] == "data: [DONE]"
    assert len(lines) == len(chunks) + 1
    assert upstream.ledger["success"] == 1
    assert upstream.ledger["model_errors"] == []


async def test_finish_reason_on_a_later_choice_counts(upstream):
    oc = upstream([_chunk("hi"), _chunk(extra_choice_finish="stop")])
    lines, error = await _collect(oc)
    assert error is None and lines[-1] == "data: [DONE]"


async def test_sdk_exception_is_still_reported_once_and_not_truncation(upstream):
    exc = openai.APIConnectionError(request=_REQ)
    oc = upstream([_chunk("hi")], raises=exc)
    lines, error = await _collect(oc)
    assert error is not None and error.mapped.message != TRUNCATED_STREAM_MESSAGE
    assert len(upstream.ledger["model_errors"]) == 1


# --- endpoint layer --------------------------------------------------------------------------


def test_text_then_clean_close_is_one_error_event_and_nothing_after(upstream):
    upstream([_chunk("hi")])
    res = _post()
    assert res.status_code == 200  # the stream had already begun
    events = _events(res.text)
    assert events.count("error") == 1 and events[-1] == "error"
    assert "message_stop" not in events and "message_delta" not in events
    block = res.text.split("event: error\ndata: ", 1)[1]
    assert block.endswith("\n\n")
    assert json.loads(block[:-2]) == {
        "type": "error",
        "error": {"type": "api_error", "message": TRUNCATED_STREAM_MESSAGE},
    }


def test_zero_chunks_is_a_real_http_502_envelope(upstream):
    upstream([])
    res = _post()
    assert res.status_code == 502
    assert res.json() == {
        "type": "error",
        "error": {"type": "api_error", "message": TRUNCATED_STREAM_MESSAGE},
    }
    assert "message_start" not in res.text


def test_normal_stream_through_the_endpoint_still_completes(upstream):
    upstream([_chunk("hi"), _chunk(finish="stop"), _chunk(choices=False, usage=True)])
    res = _post()
    assert res.status_code == 200
    events = _events(res.text)
    assert events[-1] == "message_stop" and "error" not in events


# --- lone surrogates -------------------------------------------------------------------------

BAD = "bad \ud800 text"


def _bad_error():
    resp = httpx.Response(400, request=_REQ)
    return openai.BadRequestError(BAD, response=resp, body={"error": {"message": BAD}})


def test_non_stream_400_with_lone_surrogate_is_a_valid_envelope(upstream, monkeypatch):
    oc = upstream([])

    async def _raise(**kwargs):
        raise _bad_error()

    monkeypatch.setattr(oc.client.chat.completions, "create", _raise)
    res = _post(stream=False)
    assert res.status_code == 400
    assert res.json() == {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "bad � text"},
    }


def test_midstream_lone_surrogate_yields_one_valid_error_event(upstream):
    upstream([_chunk("hi")], raises=_bad_error())
    res = _post()
    assert _events(res.text).count("error") == 1
    block = res.text.split("event: error\ndata: ", 1)[1]
    assert json.loads(block[:-2])["error"]["message"] == "bad � text"
    res.text.encode("utf-8")
