"""Shared upstream-error mapping: OpenAI-SDK exception -> Anthropic error contract.

This module must stay free of ``src.core.config`` / ``src.core.client`` imports so both can use it.
"""

import json
import re
from typing import Any, Dict, Iterable, NamedTuple, Optional

from fastapi import HTTPException
from openai._exceptions import APIError, AuthenticationError, RateLimitError

PROMPT_TOO_LONG_PREFIX = "capability_rejected: prompt_too_long "

_TYPE_BY_STATUS = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    429: "rate_limit_error",
    500: "api_error",
    529: "overloaded_error",
}

_PROMPT_TOO_LONG_TRIGGERS = (
    "context_length_exceeded",
    "maximum context length",
    "string too long",
    "context window",
    "too many tokens",
)

_FORWARDED_EXACT = ("x-should-retry", "request-id", "x-request-id")
_FORWARDED_PREFIX = "anthropic-ratelimit-unified-"
_RETRY_AFTER_RE = re.compile(r"[0-9]{1,10}", re.ASCII)
_SAFE_HEADER_RE = re.compile(r"[\x20-\x7e]*", re.ASCII)
_MAX_HEADER_VALUE_LEN = 256
MIN_REDACT_KEY_LEN = 8


class MappedError(NamedTuple):
    status: int
    error_type: str
    message: str
    headers: Dict[str, str]
    retryable: bool
    counts_as_model_failure: bool


def counts_as_model_failure(status: int, text: str) -> bool:
    """Whether an upstream failure should count against the active model (fallback accounting)."""
    error_str = str(text).lower()
    return bool(
        status == 429
        or status == 503
        or "rate_limit" in error_str
        or "model" in error_str
        and (
            "not found" in error_str or "does not exist" in error_str or "unavailable" in error_str
        )
        or "overloaded" in error_str
        or "capacity" in error_str
    )


def error_type_for_status(status: int) -> str:
    if status in _TYPE_BY_STATUS:
        return _TYPE_BY_STATUS[status]
    if 400 <= status < 500:
        return "invalid_request_error"
    return "api_error"


def error_envelope(error_type: str, message: str) -> dict:
    return {"type": "error", "error": {"type": error_type, "message": message}}


def error_json(error_type: str, message: str) -> str:
    return json.dumps(error_envelope(error_type, message), ensure_ascii=False)


def _status_of(exc: BaseException) -> int:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status
    if isinstance(exc, AuthenticationError):
        return 401
    if isinstance(exc, RateLimitError):
        return 429
    return 500


def _upstream_text(exc: APIError) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        candidate = err.get("message") if isinstance(err, dict) else None
        if not (isinstance(candidate, str) and candidate.strip()):
            candidate = body.get("message")
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    for text in (getattr(exc, "message", None), str(exc)):
        if isinstance(text, str) and text.strip():
            return text
    return ""


def _forwarded_headers(exc: BaseException) -> Dict[str, str]:
    response = getattr(exc, "response", None)
    raw = getattr(response, "headers", None)
    if raw is None:
        return {}
    out: Dict[str, str] = {}
    try:
        items = list(raw.items())
    except Exception:  # noqa: BLE001 - odd header container; forward nothing
        return {}
    for name, value in items:
        key = str(name).lower()
        value = str(value)
        if key == "retry-after":
            if _RETRY_AFTER_RE.fullmatch(value.strip()):
                out[key] = value.strip()
        elif key in _FORWARDED_EXACT or key.startswith(_FORWARDED_PREFIX):
            # Upstream-controlled: keep only printable ASCII so Starlette's latin-1 header
            # encoding can never fail (and CR/LF can never be smuggled in).
            if len(value) <= _MAX_HEADER_VALUE_LEN and _SAFE_HEADER_RE.fullmatch(value):
                out[key] = value
    return out


def redact_keys(text: str, keys: Iterable[Optional[str]]) -> str:
    """Replace every occurrence of each key (>= MIN_REDACT_KEY_LEN chars) with ``[redacted]``."""
    usable = {k for k in keys if isinstance(k, str) and len(k) >= MIN_REDACT_KEY_LEN}
    for key in sorted(usable, key=len, reverse=True):
        text = text.replace(key, "[redacted]")
    return text


def map_upstream_error(
    exc: BaseException,
    api_key: Optional[str] = None,
    extra_keys: Iterable[Optional[str]] = (),
) -> MappedError:
    """Translate an upstream exception into status, Anthropic type, message and headers.

    ``api_key`` and ``extra_keys`` (for example the whole provider pool) are scrubbed from the
    message. Keys shorter than MIN_REDACT_KEY_LEN are ignored.
    """
    if not isinstance(exc, APIError):
        status = 500
        message = "Unexpected error: " + str(exc)
        headers: Dict[str, str] = {}
        text_for_rule = str(exc)
    else:
        status = _status_of(exc)
        message = _upstream_text(exc)
        if not message.strip():
            message = f"Upstream error (HTTP {status})"
        headers = _forwarded_headers(exc)
        text_for_rule = str(exc)

    message = redact_keys(message, [api_key, *extra_keys])

    if status in (400, 413) and isinstance(exc, APIError):
        haystack = (message + str(exc)).lower()
        if getattr(exc, "code", None) == "context_length_exceeded" or any(
            t in haystack for t in _PROMPT_TOO_LONG_TRIGGERS
        ):
            message = PROMPT_TOO_LONG_PREFIX + message

    should_retry = headers.get("x-should-retry", "").strip().lower()
    if should_retry in ("true", "false"):
        retryable = should_retry == "true"
    else:
        retryable = status in (408, 409, 429) or status >= 500

    return MappedError(
        status=status,
        error_type=error_type_for_status(status),
        message=message,
        headers=headers,
        retryable=retryable,
        counts_as_model_failure=counts_as_model_failure(status, text_for_rule),
    )


class UpstreamError(Exception):
    """A mapped upstream failure. Deliberately not an HTTPException (used on the stream path)."""

    def __init__(self, mapped: MappedError):
        super().__init__(mapped.message)
        self.mapped = mapped

    def __str__(self) -> str:
        return self.mapped.message


class UpstreamHTTPError(UpstreamError, HTTPException):
    """Mapped upstream failure for the non-stream path; FastAPI renders it with real status."""

    def __init__(self, mapped: MappedError):
        HTTPException.__init__(
            self,
            status_code=mapped.status,
            detail=mapped.message,
            headers=mapped.headers or None,
        )
        self.mapped = mapped

    def __str__(self) -> str:
        return self.mapped.message
