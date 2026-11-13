"""Content-free request "signal" log for the auto-model groundwork.

Opt-in (``AUTO_SIGNAL_LOG``), append-only, one single-line JSON record per
request in ``logs/auto_signal.log``. The record holds only field/header NAMES,
counts, booleans, enum-filtered values and two short hashes; it never holds
message/system/tool text, tool names or schemas, base64 data or header values.

Everything here is best-effort: a failure while building or writing a record is
logged at DEBUG on the ``proxy`` logger and never raised into a request.
This module reads ``os.environ`` at call time and imports nothing from
``src.core.config`` / ``src.core.logging``.
"""

import hashlib
import json
import logging
import os
import re
import threading
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional

_SIGNAL_LOGGER_NAME = "auto_signal"
_LINE_PREFIX = "AUTOSIGNAL "

_DEFAULT_MAX_BYTES = 5242880
_DEFAULT_BACKUP_COUNT = 3

_TRUTHY = {"1", "true", "yes", "on"}
_EFFORT_ENUM = {"low", "medium", "high", "xhigh", "max"}
_THINK_ENUM = {"enabled", "disabled", "adaptive"}
_REQ_CLASS_ENUM = {"main", "subagent", "workflow", "compaction", "auxiliary"}

_STR_CAP = 64
_LIST_CAP = 50
_FM_HASH_CHARS = 512
_HASH_HEX_CHARS = 8

_REMINDER_RE = re.compile(r"<system-reminder>.*?(?:</system-reminder>|\Z)", re.DOTALL)

_lock = threading.Lock()


def _debug_logger() -> logging.Logger:
    return logging.getLogger("proxy")


# ---------------------------------------------------------------------------
# Configuration helpers (env read at call time)
# ---------------------------------------------------------------------------
def _enabled() -> bool:
    return os.environ.get("AUTO_SIGNAL_LOG", "").strip().lower() in _TRUTHY


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip())
    except (ValueError, AttributeError):
        return default
    return value if value > 0 else default


def _log_path() -> str:
    # Same project-root derivation as src/core/logging.py.
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(script_dir)
    return os.path.join(project_root, "logs", "auto_signal.log")


# ---------------------------------------------------------------------------
# Small safe-access helpers (work for pydantic models and plain dicts)
# ---------------------------------------------------------------------------
def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _cap(value: Any) -> str:
    return str(value)[:_STR_CAP]


def _names(values: Any) -> List[str]:
    return sorted(_cap(v) for v in values)[:_LIST_CAP]


def _enum_or_other(value: Any, allowed: set) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower()
    return "other"


def _hash(prefix: str, text: str) -> str:
    digest = hashlib.sha256((prefix + text).encode("utf-8", "replace")).hexdigest()
    return digest[:_HASH_HEX_CHARS]


def _jdump(value: Any) -> str:
    return json.dumps(value, default=str)


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------
def _text_of(content: Any) -> str:
    """Concatenate text from a str / list-of-blocks / dict tool_result content."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    if isinstance(content, list):
        return "".join(_text_of(item) for item in content)
    return ""


def _block_chars(block: Any) -> int:
    """Characters a content block contributes to the size estimate."""
    btype = _get(block, "type")
    if btype == "text":
        text = _get(block, "text")
        return len(text) if isinstance(text, str) else 0
    if btype == "tool_use":
        return len(_jdump(_get(block, "input")))
    if btype == "tool_result":
        return len(_text_of(_get(block, "content")))
    return 0  # image (base64 excluded) and unknown blocks (thinking, ...)


def _count_images(blocks: Any) -> int:
    count = 0
    if not isinstance(blocks, list):
        return 0
    for block in blocks:
        btype = _get(block, "type")
        if btype == "image":
            count += 1
        elif btype == "tool_result":
            count += _count_images(_get(block, "content"))
    return count


def _estimate_tokens(request: Any) -> int:
    chars = 0
    system = _get(request, "system")
    if isinstance(system, str):
        chars += len(system)
    elif isinstance(system, list):
        chars += sum(_block_chars(b) for b in system)
    for message in _get(request, "messages") or []:
        content = _get(message, "content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            chars += sum(_block_chars(b) for b in content)
    for tool in _get(request, "tools") or []:
        chars += len(
            _jdump(
                [
                    _get(tool, "name"),
                    _get(tool, "description"),
                    _get(tool, "input_schema"),
                ]
            )
        )
    return chars // 4


def _first_message_hash(messages: Any) -> Dict[str, Any]:
    """Hash of the first user message's text, with injected reminders removed."""
    out = {"fm_stripped": False}  # type: Dict[str, Any]
    first = None
    for message in messages or []:
        if _get(message, "role") == "user":
            first = message
            break
    if first is None:
        return out
    content = _get(first, "content")
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = []
        for block in content:
            if _get(block, "type") == "text":
                text = _get(block, "text")
                if isinstance(text, str):
                    texts.append(text)
    else:
        texts = []
    kept = []
    for text in texts:
        stripped = _REMINDER_RE.sub("", text)
        if stripped != text:
            out["fm_stripped"] = True
        kept.append(stripped)
    normalized = " ".join("\n".join(kept).split())
    if normalized:
        out["fm_hash"] = _hash("msg:", normalized[:_FM_HASH_CHARS])
    return out


def _header_map(headers: Any) -> Dict[str, str]:
    """Lowercased name -> first value. Values are only used for hashing/flags."""
    result = {}  # type: Dict[str, str]
    if headers is None:
        return result
    try:
        pairs = list(headers.items())
    except Exception:
        return result
    for name, value in pairs:
        key = str(name).lower()
        if key not in result:
            result[key] = value if isinstance(value, str) else str(value)
    return result


def build_signal_record(request: Any, headers: Any, is_auto_alias: bool) -> Dict[str, Any]:
    """Build the content-free record. Pure; never raises."""
    rec = {}  # type: Dict[str, Any]

    def section(fn: Any) -> None:
        try:
            fn()
        except Exception as exc:  # pragma: no cover - defensive
            _debug_logger().debug("signal_log: record section failed: %s", type(exc).__name__)

    hdrs = _header_map(headers)
    extra = None

    def basics() -> None:
        nonlocal extra
        fields = set(_get(request, "model_fields_set") or ())
        extra = _get(request, "model_extra")
        if isinstance(extra, dict):
            fields |= set(extra.keys())
        rec["body_fields"] = _names(fields)
        rec["header_names"] = _names(hdrs.keys())
        rec["model"] = _cap(_get(request, "model", ""))
        rec["auto"] = bool(is_auto_alias)
        rec["stream"] = bool(_get(request, "stream"))
        max_tokens = _get(request, "max_tokens")
        rec["max_tokens"] = (
            max_tokens if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) else None
        )

    def counts() -> None:
        messages = list(_get(request, "messages") or [])
        rec["msgs"] = len(messages)
        last_tool_result = False
        if messages:
            content = _get(messages[-1], "content")
            if isinstance(content, list):
                last_tool_result = any(_get(b, "type") == "tool_result" for b in content)
        rec["last_tool_result"] = last_tool_result
        rec["tools"] = len(_get(request, "tools") or [])
        images = 0
        for message in messages:
            images += _count_images(_get(message, "content"))
        rec["images"] = images

    def effort() -> None:
        rec["reasoning_effort"] = _enum_or_other(_get(request, "reasoning_effort"), _EFFORT_ENUM)
        output_config = extra.get("output_config") if isinstance(extra, dict) else None
        if isinstance(output_config, dict):
            rec["oc_keys"] = _names(output_config.keys())
            rec["oc_effort"] = _enum_or_other(output_config.get("effort"), _EFFORT_ENUM)
        else:
            rec["oc_keys"] = []
            rec["oc_effort"] = None

    def thinking() -> None:
        think = _get(request, "thinking")
        rec["think_type"] = (
            None if think is None else _enum_or_other(_get(think, "type") or "", _THINK_ENUM)
        )
        budget = _get(think, "budget_tokens")
        rec["think_budget"] = (
            budget if isinstance(budget, int) and not isinstance(budget, bool) else None
        )

    def header_flags() -> None:
        rec["beta"] = "anthropic-beta" in hdrs
        sid = hdrs.get("x-claude-code-session-id")
        rec["sid"] = sid is not None
        if sid is not None:
            rec["sid_hash"] = _hash("sid:", sid)
        rec["agent"] = "x-claude-code-agent-id" in hdrs
        rec["parent_agent"] = "x-claude-code-parent-agent-id" in hdrs
        req_class = hdrs.get("x-claude-code-request-class")
        rec["req_class"] = _enum_or_other(req_class, _REQ_CLASS_ENUM)

    def meta() -> None:
        metadata = _get(request, "metadata")
        rec["meta"] = metadata is not None
        rec["meta_keys"] = _names(metadata.keys()) if isinstance(metadata, dict) else []

    def size() -> None:
        rec["est_tokens"] = _estimate_tokens(request)

    def first_message() -> None:
        rec.update(_first_message_hash(_get(request, "messages")))

    for fn in (basics, counts, effort, thinking, header_flags, meta, size, first_message):
        section(fn)
    return rec


# ---------------------------------------------------------------------------
# Logger / handler
# ---------------------------------------------------------------------------
class _SignalFileHandler(RotatingFileHandler):
    """Rotating handler that reports I/O failures at DEBUG instead of stderr."""

    def handleError(self, record: logging.LogRecord) -> None:
        _debug_logger().debug("signal_log: write failed")


def _ensure_handler() -> logging.Logger:
    logger = logging.getLogger(_SIGNAL_LOGGER_NAME)
    if logger.handlers:
        return logger
    with _lock:
        if logger.handlers:
            return logger
        path = _log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handler = _SignalFileHandler(
            path,
            mode="a",
            maxBytes=_int_env("AUTO_SIGNAL_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES),
            backupCount=_int_env("AUTO_SIGNAL_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT),
            encoding="utf-8",
            delay=True,
        )
        handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
    return logger


def emit_signal(request: Any, headers: Any, is_auto_alias: bool) -> None:
    """Append one record to the signal log. No-op unless enabled; never raises."""
    try:
        if not _enabled():
            return
        record = build_signal_record(request, headers, is_auto_alias)
        line = _LINE_PREFIX + json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        _ensure_handler().info(line)
    except Exception as exc:
        try:
            _debug_logger().debug("signal_log: emit failed: %s", type(exc).__name__)
        except Exception:
            pass


def reset_for_tests() -> None:
    """Close and remove the signal logger's handlers (tests only)."""
    logger = logging.getLogger(_SIGNAL_LOGGER_NAME)
    with _lock:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
