"""Tests for STREAM_MAX_RETRIES parsing and the stream flag on get_next_client_async."""

import asyncio
import logging

import pytest


def _make_config(monkeypatch, stream=None, max_retries=None):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for name, val in (("STREAM_MAX_RETRIES", stream), ("MAX_RETRIES", max_retries)):
        if val is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, val)
    import src.core.config as cfg

    return cfg.Config()


def _warnings(caplog):
    return [r for r in caplog.records if r.name == "config" and r.levelno == logging.WARNING]


def test_default_is_zero_and_max_retries_unchanged(monkeypatch):
    cfg = _make_config(monkeypatch)
    assert cfg.stream_max_retries == 0
    assert cfg.max_retries == 2


def test_empty_value_is_zero_silently(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="config"):
        assert _make_config(monkeypatch, stream="  ").stream_max_retries == 0
    assert not _warnings(caplog)


@pytest.mark.parametrize("raw,expected", [("2", 2), ("0", 0), (" 3 ", 3)])
def test_valid_values_honoured(monkeypatch, raw, expected):
    assert _make_config(monkeypatch, stream=raw).stream_max_retries == expected


def test_negative_falls_back_with_warning(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="config"):
        cfg = _make_config(monkeypatch, stream="-1")
    assert cfg.stream_max_retries == 0
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "STREAM_MAX_RETRIES" in warns[0].getMessage()


@pytest.mark.parametrize("raw", ["abc", "1.5", "true"])
def test_non_integer_falls_back_with_warning(monkeypatch, caplog, raw):
    with caplog.at_level(logging.WARNING, logger="config"):
        cfg = _make_config(monkeypatch, stream=raw)
    assert cfg.stream_max_retries == 0
    warns = _warnings(caplog)
    assert len(warns) == 1
    assert "STREAM_MAX_RETRIES" in warns[0].getMessage()


def test_stream_flag_selects_budget_default_zero(monkeypatch):
    cfg = _make_config(monkeypatch, stream="0", max_retries="4")
    assert asyncio.run(cfg.get_next_client_async(stream=True)).client.max_retries == 0
    assert asyncio.run(cfg.get_next_client_async()).client.max_retries == 4
    assert asyncio.run(cfg.get_next_client_async(stream=False)).client.max_retries == 4


def test_stream_and_non_stream_are_separate(monkeypatch):
    cfg = _make_config(monkeypatch, stream="3", max_retries="1")
    assert asyncio.run(cfg.get_next_client_async(stream=True)).client.max_retries == 3
    assert asyncio.run(cfg.get_next_client_async(stream=False)).client.max_retries == 1


def test_sync_getter_unchanged(monkeypatch):
    cfg = _make_config(monkeypatch, stream="3", max_retries="1")
    assert cfg.get_next_client().client.max_retries == cfg.max_retries == 1


def test_stream_is_keyword_only(monkeypatch):
    cfg = _make_config(monkeypatch)
    with pytest.raises(TypeError):
        asyncio.run(cfg.get_next_client_async(True))
