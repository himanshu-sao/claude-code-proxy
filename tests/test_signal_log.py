"""Tests for the content-free auto-signal log (src/core/signal_log.py) and its analyzer.

All tests point the module at a path under tmp_path (monkeypatched ``_log_path``) and set
env via monkeypatch, so the real ``logs/`` directory is never touched.
"""

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.core import signal_log
from src.models.claude import ClaudeMessagesRequest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "analyze_signal_log.py"


def _sha8(prefix, text):
    return hashlib.sha256((prefix + text).encode("utf-8")).hexdigest()[:8]


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "logs" / "auto_signal.log"
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(path))
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    monkeypatch.delenv("AUTO_SIGNAL_LOG_MAX_BYTES", raising=False)
    monkeypatch.delenv("AUTO_SIGNAL_LOG_BACKUP_COUNT", raising=False)
    signal_log.reset_for_tests()
    yield path
    signal_log.reset_for_tests()


def _req(**overrides):
    body = {
        "model": "claude-proxy-auto",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "hello world"}],
    }
    body.update(overrides)
    return ClaudeMessagesRequest(**body)


def _lines(path):
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln]


def _record(line):
    assert "AUTOSIGNAL " in line
    return json.loads(line.split("AUTOSIGNAL ", 1)[1])


# --- 1. disabled -------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "0", "false", "off", "no", "maybe"])
def test_disabled_does_nothing(log_file, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("AUTO_SIGNAL_LOG", raising=False)
    else:
        monkeypatch.setenv("AUTO_SIGNAL_LOG", value)
    signal_log.emit_signal(_req(), {}, True)
    assert logging.getLogger("auto_signal").handlers == []
    assert not log_file.parent.exists()
    assert not log_file.exists()


# --- 2. one line per call, no propagation ------------------------------------


def test_one_line_per_call_and_no_propagation(log_file):
    captured = []

    class Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    root = logging.getLogger()
    cap = Capture(level=logging.DEBUG)
    root.addHandler(cap)
    try:
        req = _req(messages=[{"role": "user", "content": "line one\nline two\r\nthree"}])
        for _ in range(3):
            signal_log.emit_signal(req, {"X-Test": "a\nb"}, False)
    finally:
        root.removeHandler(cap)
    lines = _lines(log_file)
    assert len(lines) == 3
    assert all("AUTOSIGNAL " in ln for ln in lines)
    assert [r for r in captured if r.name == "auto_signal"] == []
    assert logging.getLogger("auto_signal").propagate is False


# --- 3/4. sentinel + field values --------------------------------------------


def test_sentinels_never_appear_and_fields_are_correct(log_file):
    sid = "SENTINEL-SESSION-ID-123"
    s = {
        k: "SENTINEL_" + k
        for k in (
            "sys_str",
            "sys_list",
            "user",
            "tu_input_key",
            "tu_input_val",
            "tool_name",
            "tool_desc",
            "prop_name",
            "prop_val",
            "tr_text",
            "b64",
            "meta_val",
            "extra_val",
            "oc_effort",
            "class",
            "apikey",
            "auth",
            "beta",
            "oc_other_val",
        )
    }
    b64 = s["b64"] + ("A" * 5000)
    body = dict(
        system=[{"type": "text", "text": s["sys_list"] + " system text"}],
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": s["user"]},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": b64},
                    },
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "SENTINEL_thinking", "signature": "x"},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": s["tool_name"],
                        "input": {s["tu_input_key"]: s["tu_input_val"]},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": s["tr_text"]},
                ],
            },
        ],
        tools=[
            {
                "name": s["tool_name"],
                "description": s["tool_desc"],
                "input_schema": {
                    "type": "object",
                    "properties": {
                        s["prop_name"]: {"type": "string", "description": s["prop_val"]}
                    },
                },
            }
        ],
        metadata={"user_id": s["meta_val"]},
        thinking={"type": "enabled", "budget_tokens": 2048},
        stream=True,
        output_config={"effort": s["oc_effort"], "format": s["oc_other_val"]},
        custom_extra_field=s["extra_val"],
        reasoning_effort="xhigh",
    )
    req = _req(**body)
    headers = {
        "X-Api-Key": s["apikey"],
        "Authorization": "Bearer " + s["auth"],
        "Anthropic-Beta": s["beta"],
        "X-Claude-Code-Session-Id": sid,
        "x-claude-code-request-class": s["class"],
        "X-Claude-Code-Agent-Id": "agent-secret-id",
    }
    signal_log.emit_signal(req, headers, True)
    lines = _lines(log_file)
    assert len(lines) == 1
    line = lines[0]
    for value in list(s.values()) + [sid, "agent-secret-id", "SENTINEL_thinking", "Bearer"]:
        assert value not in line, value
    assert "AAAAAAAA" not in line
    rec = _record(line)

    assert rec["sid_hash"] == _sha8("sid:", sid)
    assert rec["sid"] is True
    assert rec["body_fields"] == sorted(
        [
            "model",
            "max_tokens",
            "messages",
            "system",
            "tools",
            "metadata",
            "thinking",
            "stream",
            "output_config",
            "custom_extra_field",
            "reasoning_effort",
        ]
    )
    assert rec["header_names"] == sorted(h.lower() for h in headers)
    assert rec["model"] == "claude-proxy-auto"
    assert rec["auto"] is True
    assert rec["stream"] is True
    assert rec["max_tokens"] == 1024
    assert rec["msgs"] == 3
    assert rec["last_tool_result"] is True
    assert rec["tools"] == 1
    assert rec["images"] == 1
    assert rec["reasoning_effort"] == "xhigh"
    assert rec["oc_effort"] == "other"
    assert rec["oc_keys"] == ["effort", "format"]
    assert rec["think_type"] == "enabled"
    assert rec["think_budget"] == 2048
    assert rec["beta"] is True
    assert rec["agent"] is True
    assert rec["parent_agent"] is False
    assert rec["req_class"] == "other"
    assert rec["meta"] is True
    assert rec["meta_keys"] == ["user_id"]
    assert rec["est_tokens"] > 0
    assert rec["est_tokens"] < 1000  # the 5000-char base64 payload is excluded
    assert rec["fm_hash"] == _sha8("msg:", s["user"])
    assert rec["fm_stripped"] is False


def test_enum_values_are_logged_when_known():
    rec = signal_log.build_signal_record(
        _req(
            output_config={"effort": "MAX"}, reasoning_effort="low", thinking={"type": "adaptive"}
        ),
        {"x-claude-code-request-class": "Subagent"},
        False,
    )
    assert rec["oc_effort"] == "max"
    assert rec["reasoning_effort"] == "low"
    assert rec["think_type"] == "adaptive"
    assert rec["think_budget"] is None
    assert rec["req_class"] == "subagent"
    assert rec["auto"] is False


def test_est_tokens_counts_system_tools_and_tool_input():
    base = signal_log.build_signal_record(_req(), {}, False)["est_tokens"]
    big = signal_log.build_signal_record(
        _req(
            system="s" * 400,
            tools=[{"name": "t", "description": "d" * 400, "input_schema": {"type": "object"}}],
        ),
        {},
        False,
    )["est_tokens"]
    assert big - base >= 200


# --- 5. hashes ----------------------------------------------------------------


def _fm(messages):
    return signal_log.build_signal_record(_req(messages=messages), {}, False)


def test_reminder_stripping_gives_same_hash_inline_and_as_block():
    plain = _fm([{"role": "user", "content": "fix the bug"}])
    inline = _fm(
        [
            {
                "role": "user",
                "content": "<system-reminder>\nCLAUDE.md says x\ndate 2026\n</system-reminder>\n"
                "fix   the\nbug",
            }
        ]
    )
    block = _fm(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<system-reminder>other stuff</system-reminder>"},
                    {"type": "text", "text": "fix the bug"},
                ],
            }
        ]
    )
    assert plain["fm_hash"] == inline["fm_hash"] == block["fm_hash"]
    assert plain["fm_stripped"] is False
    assert inline["fm_stripped"] is True
    assert block["fm_stripped"] is True


def test_unclosed_reminder_deletes_to_end():
    rec = _fm([{"role": "user", "content": "keep <system-reminder> never closed secret"}])
    assert rec["fm_hash"] == _sha8("msg:", "keep")
    assert rec["fm_stripped"] is True


def test_different_text_different_hash_and_domain_prefix():
    a = _fm([{"role": "user", "content": "alpha"}])
    b = _fm([{"role": "user", "content": "beta"}])
    assert a["fm_hash"] != b["fm_hash"]
    assert _sha8("msg:", "alpha") != _sha8("sid:", "alpha")


def test_hash_uses_first_user_message_only():
    one = _fm(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "x"},
            {"role": "user", "content": "second"},
        ]
    )
    two = _fm([{"role": "user", "content": "first"}])
    assert one["fm_hash"] == two["fm_hash"] == _sha8("msg:", "first")
    # An assistant message before the first user message is skipped.
    three = _fm([{"role": "assistant", "content": "hi"}, {"role": "user", "content": "first"}])
    assert three["fm_hash"] == one["fm_hash"]


def test_only_first_512_chars_are_hashed():
    a = _fm([{"role": "user", "content": "x" * 512 + "tail-a"}])
    b = _fm([{"role": "user", "content": "x" * 512 + "tail-b"}])
    assert a["fm_hash"] == b["fm_hash"]


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "assistant", "content": "only assistant"}],
        [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t", "content": "res"}],
            }
        ],
        [{"role": "user", "content": ""}],
        [{"role": "user", "content": "<system-reminder>only reminder</system-reminder>"}],
    ],
)
def test_fm_hash_omitted(messages):
    assert "fm_hash" not in _fm(messages)


def test_sid_hash_omitted_without_header():
    rec = signal_log.build_signal_record(_req(), {"user-agent": "x"}, False)
    assert "sid_hash" not in rec
    assert rec["sid"] is False


# --- 6. builder robustness ----------------------------------------------------


def test_builder_robustness_variants():
    variants = [
        dict(system=None),
        dict(system=[{"type": "text", "text": "a"}]),
        dict(tools=None),
        dict(metadata=None),
        dict(thinking={"type": "adaptive"}),
        dict(messages=[]),
        dict(
            messages=[
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "t", "signature": "s"},
                        {"type": "redacted_thinking", "data": "d"},
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "x",
                            "content": [{"type": "text", "text": "abc"}],
                        }
                    ],
                },
            ]
        ),
    ]
    for extra in variants:
        assert isinstance(signal_log.build_signal_record(_req(**extra), {}, False), dict)
    assert isinstance(signal_log.build_signal_record(_req(), None, False), dict)

    # Duplicate headers (list of pairs behaves like starlette Headers.items()).
    class Dup:
        def items(self):
            return [("X-Claude-Code-Session-Id", "one"), ("x-claude-code-session-id", "two")]

    rec = signal_log.build_signal_record(_req(), Dup(), False)
    assert rec["header_names"] == ["x-claude-code-session-id"]
    assert rec["sid_hash"] == _sha8("sid:", "one")
    # Things that are not requests at all still return a dict.
    assert isinstance(signal_log.build_signal_record(object(), object(), False), dict)
    assert isinstance(signal_log.build_signal_record(None, None, False), dict)


def test_builder_handles_5mb_body():
    big = "z" * (5 * 1024 * 1024)
    rec = signal_log.build_signal_record(
        _req(messages=[{"role": "user", "content": big}]), {}, False
    )
    assert isinstance(rec, dict)
    assert rec["est_tokens"] >= 5 * 1024 * 1024 // 4


def test_emit_with_raising_builder_logs_nothing(log_file, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(signal_log, "build_signal_record", boom)
    signal_log.emit_signal(_req(), {}, False)
    assert _lines(log_file) == []


# --- 7. append / restart / race ----------------------------------------------


def test_reset_then_emit_keeps_earlier_lines(log_file):
    signal_log.emit_signal(_req(), {}, False)
    signal_log.reset_for_tests()
    assert logging.getLogger("auto_signal").handlers == []
    signal_log.emit_signal(_req(), {}, False)
    assert len(_lines(log_file)) == 2


def test_concurrent_first_emit_creates_one_handler(log_file):
    barrier = threading.Barrier(2)

    def work():
        barrier.wait()
        signal_log.emit_signal(_req(), {}, False)

    threads = [threading.Thread(target=work) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(logging.getLogger("auto_signal").handlers) == 1
    assert len(_lines(log_file)) == 2


# --- 8. rotation / env fallbacks ----------------------------------------------


def test_rotation_keeps_backup_count(log_file, monkeypatch):
    monkeypatch.setenv("AUTO_SIGNAL_LOG_MAX_BYTES", "300")
    monkeypatch.setenv("AUTO_SIGNAL_LOG_BACKUP_COUNT", "2")
    for _ in range(40):
        signal_log.emit_signal(_req(), {}, False)
    names = sorted(p.name for p in log_file.parent.iterdir())
    assert names == ["auto_signal.log", "auto_signal.log.1", "auto_signal.log.2"]


@pytest.mark.parametrize("bad", ["abc", "0", "-5", ""])
def test_invalid_env_values_fall_back(log_file, monkeypatch, bad):
    monkeypatch.setenv("AUTO_SIGNAL_LOG_MAX_BYTES", bad)
    monkeypatch.setenv("AUTO_SIGNAL_LOG_BACKUP_COUNT", bad)
    assert signal_log._int_env("AUTO_SIGNAL_LOG_MAX_BYTES", 5242880) == 5242880
    assert signal_log._int_env("AUTO_SIGNAL_LOG_BACKUP_COUNT", 3) == 3
    signal_log.emit_signal(_req(), {}, False)
    assert len(_lines(log_file)) == 1
    handler = logging.getLogger("auto_signal").handlers[0]
    assert handler.maxBytes == 5242880
    assert handler.backupCount == 3


def test_valid_env_values_are_used(log_file, monkeypatch):
    monkeypatch.setenv("AUTO_SIGNAL_LOG_MAX_BYTES", "1234")
    monkeypatch.setenv("AUTO_SIGNAL_LOG_BACKUP_COUNT", "7")
    signal_log.emit_signal(_req(), {}, False)
    handler = logging.getLogger("auto_signal").handlers[0]
    assert (handler.maxBytes, handler.backupCount) == (1234, 7)


# --- 9. missing / unwritable path ----------------------------------------------


def test_missing_directory_is_created(tmp_path, monkeypatch):
    path = tmp_path / "a" / "b" / "logs" / "auto_signal.log"
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(path))
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "true")
    signal_log.reset_for_tests()
    try:
        signal_log.emit_signal(_req(), {}, False)
        assert len(_lines(path)) == 1
    finally:
        signal_log.reset_for_tests()


def test_file_where_directory_should_be_is_swallowed(tmp_path, monkeypatch, capfd):
    blocker = tmp_path / "logs"
    blocker.write_text("i am a file")
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(blocker / "auto_signal.log"))
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    signal_log.reset_for_tests()
    try:
        signal_log.emit_signal(_req(), {}, False)
        signal_log.emit_signal(_req(), {}, False)
    finally:
        signal_log.reset_for_tests()
    assert "Traceback" not in capfd.readouterr().err
    assert blocker.read_text() == "i am a file"


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0, reason="read-only dirs not enforced for root"
)
def test_read_only_directory_is_swallowed(tmp_path, monkeypatch, capfd):
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o500)
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(d / "auto_signal.log"))
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    signal_log.reset_for_tests()
    try:
        signal_log.emit_signal(_req(), {}, False)
        signal_log.emit_signal(_req(), {}, False)
    finally:
        signal_log.reset_for_tests()
        d.chmod(0o700)
    assert "Traceback" not in capfd.readouterr().err
    assert list(d.iterdir()) == []


# --- 10. LOG_LEVEL independence ------------------------------------------------


def test_root_warning_level_does_not_suppress(log_file, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    root = logging.getLogger()
    old = root.level
    root.setLevel(logging.WARNING)
    try:
        signal_log.emit_signal(_req(), {}, False)
    finally:
        root.setLevel(old)
    assert len(_lines(log_file)) == 1


# --- 11/12. analyzer script ---------------------------------------------------


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + [str(a) for a in args],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=60,
    )


SECTIONS = [
    "Body field names",
    "Header names",
    "Effort and thinking presence",
    "Size, tools and max_tokens",
    "Tool-result share",
    "Request class and auxiliary/subagent share",
    "Conversation key comparison",
    "Verdict",
]


def _assert_sections(out):
    for name in SECTIONS:
        assert name in out, name


def test_analyzer_empty_garbage_missing_and_rotated(tmp_path, log_file):
    empty = tmp_path / "empty.log"
    empty.write_text("")
    garbage = tmp_path / "garbage.log"
    garbage.write_text(
        "hello\nAUTOSIGNAL not json\nAUTOSIGNAL [1,2]\nAUTOSIGNAL 5\n\x00\xff junk\n"
    )
    for target in (empty, garbage):
        res = _run(target)
        assert res.returncode == 0, res.stderr
        _assert_sections(res.stdout)

    signal_log.emit_signal(_req(), {"x-claude-code-session-id": "s1"}, True)
    res = _run(tmp_path / "nope.log", log_file)
    assert res.returncode == 0
    assert "cannot read" in res.stderr
    assert "records: 1" in res.stdout
    _assert_sections(res.stdout)

    rotated = tmp_path / "auto_signal.log.1"
    rotated.write_text(log_file.read_text(encoding="utf-8"))
    res = _run(log_file, rotated)
    assert res.returncode == 0
    assert "records: 2" in res.stdout

    res = _run()
    assert res.returncode == 2
    assert "usage" in res.stderr.lower()


def test_analyzer_separates_repeat_rate_from_constancy(log_file):
    def emit(first, sid, agent=False):
        headers = {"x-claude-code-session-id": sid}
        if agent:
            headers["x-claude-code-agent-id"] = "a1"
        signal_log.emit_signal(_req(messages=[{"role": "user", "content": first}]), headers, True)

    for sid in ("s1", "s2", "s3"):
        emit("same opening prompt", sid)
    for _ in range(4):
        emit("alpha task", "s4")
    emit("subagent brief", "s4", agent=True)

    res = _run(log_file)
    assert res.returncode == 0, res.stderr
    out = res.stdout
    shared = _sha8("msg:", "same opening prompt")
    assert "with more than 1 session: 1" in out
    assert "top group fm_hash=%s sessions=3" % shared in out
    assert "sessions whose fm_hash is shared: 3 of 4" in out
    main_idx = out.index("main-thread only")
    all_idx = out.index("all records")
    main_block = out[main_idx:all_idx]
    all_block = out[all_idx : out.index("Verdict")]
    assert "sessions with 2+ turns: 1; exactly 1 distinct fm_hash: 1 (100.0%)" in main_block
    assert "sessions with 2+ turns: 1; exactly 1 distinct fm_hash: 0 (0.0%)" in all_block
    assert "{2: 1}" in all_block
    assert "insufficient sample" in out


# --- rework round 1 ---------------------------------------------------------------------------

MARKER = "HOSTILE MARKER text"


def test_hostile_names_are_logged_as_other(log_file):
    hostile = [
        MARKER,
        "has space",
        "ctl\x1b[31m\nchar",
        "café-‮",
        "x" * 65,
        "",
    ]
    for bad in hostile:
        req = _req(
            model=bad,
            metadata={bad: "v"},
            output_config={bad: 1, "effort": "high"},
            **{bad or "empty": 1},
        )
        rec = signal_log.build_signal_record(req, {bad: "v"}, False)
        assert rec["model"] == "other", repr(bad)
        assert rec["meta_keys"] == ["other"], repr(bad)
        assert sorted(rec["oc_keys"]) == ["effort", "other"], repr(bad)
        assert ("other" in rec["body_fields"]) == (bad != ""), repr(bad)
        assert "other" in rec["header_names"] or bad == "", repr(bad)
        blob = json.dumps(rec)
        for token in ("HOSTILE", "space", "\\u00e9", "\\u202e", "xxxxxx"):
            assert token not in blob, (repr(bad), token)
    # Emit end-to-end for the marker too.
    signal_log.emit_signal(
        _req(model=MARKER, metadata={MARKER: 1}, **{MARKER: 1}), {MARKER: "v"}, False
    )
    assert "HOSTILE" not in _lines(log_file)[0]


def test_legitimate_names_pass_through():
    rec = signal_log.build_signal_record(
        _req(model="z-ai/glm-5.3:free", metadata={"user_id": "u"}),
        {"X-Claude-Code-Session-Id": "s"},
        False,
    )
    assert rec["model"] == "z-ai/glm-5.3:free"
    assert rec["meta_keys"] == ["user_id"]
    assert rec["header_names"] == ["x-claude-code-session-id"]


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="POSIX permissions only")
def test_log_file_is_created_0600(log_file):
    signal_log.emit_signal(_req(), {}, False)
    assert (log_file.stat().st_mode & 0o777) == 0o600


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="needs O_NOFOLLOW")
def test_symlink_at_log_path_is_not_followed(tmp_path, monkeypatch):
    target = tmp_path / "victim.txt"
    target.write_text("untouched")
    d = tmp_path / "logs"
    d.mkdir()
    (d / "auto_signal.log").symlink_to(target)
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(d / "auto_signal.log"))
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    signal_log.reset_for_tests()
    try:
        signal_log.emit_signal(_req(), {}, False)
        signal_log.emit_signal(_req(), {}, False)
    finally:
        signal_log.reset_for_tests()
    assert target.read_text() == "untouched"


def test_env_limits_are_clamped(log_file, monkeypatch):
    monkeypatch.setenv("AUTO_SIGNAL_LOG_BACKUP_COUNT", "5000000")
    monkeypatch.setenv("AUTO_SIGNAL_LOG_MAX_BYTES", str(10**15))
    signal_log.emit_signal(_req(), {}, False)
    handler = logging.getLogger("auto_signal").handlers[0]
    assert handler.backupCount == 20
    assert handler.maxBytes == 1073741824
    assert signal_log._int_env("AUTO_SIGNAL_LOG_BACKUP_COUNT", 3, 20) == 20
    monkeypatch.setenv("AUTO_SIGNAL_LOG_BACKUP_COUNT", "20")
    assert signal_log._int_env("AUTO_SIGNAL_LOG_BACKUP_COUNT", 3, 20) == 20
    for bad in ("abc", "0", "-5", ""):
        monkeypatch.setenv("AUTO_SIGNAL_LOG_BACKUP_COUNT", bad)
        assert signal_log._int_env("AUTO_SIGNAL_LOG_BACKUP_COUNT", 3, 20) == 3


def test_huge_and_odd_ints_do_not_drop_the_record(log_file):
    huge = ClaudeMessagesRequest(
        model="m",
        max_tokens=10**5000,
        messages=[{"role": "user", "content": "hi"}],
        thinking={"type": "enabled", "budget_tokens": 10**5000},
    )
    signal_log.emit_signal(huge, {}, False)
    lines = _lines(log_file)
    assert len(lines) == 1
    rec = _record(lines[0])
    assert rec["max_tokens"] is None
    assert rec["think_budget"] is None

    small = signal_log._small_int
    assert small(0) == 0
    assert small(2**53 - 1) == 2**53 - 1
    for bad in (2**53, -1, True, False, 1.5, "7", None):
        assert small(bad) is None, bad
    plain = signal_log.build_signal_record(
        _req(max_tokens=4096, thinking={"type": "enabled", "budget_tokens": 1024}), {}, False
    )
    assert (plain["max_tokens"], plain["think_budget"]) == (4096, 1024)
    # Floats and bools are not ints, so they are not logged (use the builder directly).
    odd = signal_log.build_signal_record(
        {"max_tokens": 1.5, "thinking": {"budget_tokens": True}}, {}, False
    )
    assert odd["max_tokens"] is None and odd["think_budget"] is None


# --- rework round 1: analyzer ------------------------------------------------------------------


def test_analyzer_survives_valid_json_garbage(tmp_path):
    path = tmp_path / "weird.log"
    path.write_text(
        "\n".join(
            [
                'AUTOSIGNAL {"sid_hash":[1],"fm_hash":[2]}',
                'AUTOSIGNAL {"sid_hash":{"a":1},"fm_hash":3}',
                'AUTOSIGNAL {"body_fields":[[1]],"header_names":[{"a":1},null,5]}',
                'AUTOSIGNAL {"req_class":[1],"reasoning_effort":{"x":1},"agent":[]}',
                "AUTOSIGNAL " + "[" * 300000,
                "AUTOSIGNAL " + '{"a":' * 100000,
                "",
            ]
        )
    )
    res = _run(path)
    assert res.returncode == 0, res.stderr[-500:]
    assert "Traceback" not in res.stderr
    _assert_sections(res.stdout)


def test_analyzer_prints_names_escaped(tmp_path):
    path = tmp_path / "ctl.log"
    path.write_text('AUTOSIGNAL {"body_fields":["\\u001b[31mRED","ok"],"header_names":["a\\nb"]}\n')
    res = _run(path)
    assert res.returncode == 0
    assert "\x1b" not in res.stdout
    assert "\\x1b[31mRED" in res.stdout


def _emit_sessions(n_sessions, turns, shared_first=None):
    for i in range(n_sessions):
        first = shared_first or "unique opening prompt %d" % i
        for _ in range(turns):
            signal_log.emit_signal(
                _req(messages=[{"role": "user", "content": first}]),
                {"x-claude-code-session-id": "sess-%d" % i},
                True,
            )


def test_analyzer_verdict_usable_with_enough_clean_sessions(log_file):
    _emit_sessions(12, 3)
    res = _run(log_file)
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "Verdict: fm_hash is usable (thresholds met)" in out
    assert "constancy >= 95%" in out and "share <= 5%" in out
    assert "at least 10 sessions" in out
    assert "constancy 100.0% (12 of 12 sessions, 36 main-thread turns)" in out
    assert "shared-session share 0.0% (0 of 12 sessions)" in out


def test_analyzer_verdict_insufficient_sample(log_file):
    _emit_sessions(1, 2)
    res = _run(log_file)
    assert res.returncode == 0, res.stderr
    assert "Verdict: fm_hash is insufficient sample" in res.stdout
    assert "usable (thresholds met)" not in res.stdout


def test_analyzer_verdict_not_usable_when_shared(log_file):
    _emit_sessions(12, 2, shared_first="the same opening prompt")
    res = _run(log_file)
    assert "NOT shown to be usable (thresholds not met)" in res.stdout


# --- rework round 2 ---------------------------------------------------------------------------


@pytest.fixture
def umask_022():
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="POSIX permissions only")
def test_created_log_directory_is_0700(tmp_path, monkeypatch, umask_022):
    path = tmp_path / "newlogs" / "auto_signal.log"
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(path))
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    signal_log.reset_for_tests()
    try:
        signal_log.emit_signal(_req(), {}, False)
    finally:
        signal_log.reset_for_tests()
    assert (path.parent.stat().st_mode & 0o777) == 0o700
    assert (path.stat().st_mode & 0o777) == 0o600


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="POSIX permissions only")
def test_existing_log_directory_is_not_tightened(tmp_path, monkeypatch, umask_022):
    d = tmp_path / "existing"
    d.mkdir()
    d.chmod(0o755)
    monkeypatch.setattr(signal_log, "_log_path", lambda: str(d / "auto_signal.log"))
    monkeypatch.setenv("AUTO_SIGNAL_LOG", "1")
    signal_log.reset_for_tests()
    try:
        signal_log.emit_signal(_req(), {}, False)
    finally:
        signal_log.reset_for_tests()
    assert (d.stat().st_mode & 0o777) == 0o755
    assert len(_lines(d / "auto_signal.log")) == 1


def test_analyzer_does_not_print_raw_escape_from_hash_values(tmp_path):
    path = tmp_path / "esc.log"
    path.write_text(
        'AUTOSIGNAL {"sid_hash":"\\u001b[31mabc","fm_hash":"\\u001b[31mdef"}\n'
        'AUTOSIGNAL {"sid_hash":"\\u001b[32m","fm_hash":"\\u001b[31mdef"}\n'
    )
    res = _run(path)
    assert res.returncode == 0, res.stderr
    assert "\x1b" not in res.stdout
    assert "\x1b" not in res.stderr
