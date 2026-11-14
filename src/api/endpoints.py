import asyncio
import os
import time
import traceback
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.conversion.request_converter import convert_claude_to_openai
from src.conversion.response_converter import (
    convert_openai_streaming_to_claude_with_cancellation,
    convert_openai_to_claude_response,
)
from src.core import signal_log
from src.core.client import OpenAIClient
from src.core.config import config
from src.core.errors import UpstreamError, error_envelope, error_type_for_status
from src.core.logging import logger
from src.core.model_manager import model_manager
from src.models.claude import ClaudeMessagesRequest, ClaudeTokenCountRequest

router = APIRouter()

# Location of the per-request state file written for the Claude Code statusline.
# Mirrors the path resolution in src/core/logging.py:28-31 so this lands next to
# proxy.log regardless of the proxy's launch directory.
_endpoints_file = os.path.abspath(__file__)
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(_endpoints_file)))
_last_model_path = os.path.join(_project_root, "logs", ".last_model")


def _write_last_model(tier: str, model: str) -> None:
    """Persist the model the proxy actually routed this request to.

    The statusline script reads logs/.last_model to display the real upstream model
    (post health-aware fallback) rather than the model Claude Code requested. Writes
    are atomic (temp file + os.replace) so a concurrent statusline read never sees a
    partial file, and any failure is swallowed — the status file must never break a
    request.
    """
    try:
        log_dir = os.path.dirname(_last_model_path)
        if not os.path.isdir(log_dir):
            return
        tmp_path = f"{_last_model_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(f"{tier}\t{model}\n")
            fh.write(f"{datetime.now().isoformat()}\n")
        os.replace(tmp_path, _last_model_path)
    except Exception as exc:  # noqa: BLE001 — status file must never break a request
        logger.debug("Failed to write .last_model: %s", exc)


def _emit_signal_safe(request: ClaudeMessagesRequest, http_request: Request) -> None:
    """Append the content-free signal record; nothing here may reach the response.

    emit_signal swallows its own failures, but its arguments are evaluated before it is
    entered, so they are evaluated inside this guard too. No-op unless AUTO_SIGNAL_LOG is on.
    """
    try:
        signal_log.emit_signal(
            request, http_request.headers, model_manager.is_auto_alias(request.model)
        )
    except Exception as exc:  # noqa: BLE001 — the signal log must never break a request
        logger.debug("signal log skipped: %s", type(exc).__name__)


# No global OpenAI client: each request obtains one from config (round-robin across keys).
# Note: config.get_next_client() is the blocking variant; never call it from async handlers.


async def validate_api_key(
    x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)
):
    """Validate the client's API key from either x-api-key header or Authorization header."""
    client_api_key = None

    # Extract API key from headers
    if x_api_key:
        client_api_key = x_api_key
    elif authorization and authorization.startswith("Bearer "):
        client_api_key = authorization.replace("Bearer ", "")

    # Skip validation if ANTHROPIC_API_KEY is not set in the environment
    if not config.anthropic_api_key:
        return

    # Validate the client API key
    if not client_api_key or not config.validate_client_api_key(client_api_key):
        logger.warning(f"Invalid API key provided by client")
        raise HTTPException(
            status_code=401, detail="Invalid API key. Please provide a valid Anthropic API key."
        )


FIRST_CHUNK_POLL_SECONDS = 0.25


class _ClientGone(Exception):
    """The client disconnected while we waited for the first upstream chunk."""


def _error_response(
    status: int, error_type: str, message: str, headers: Optional[dict] = None
) -> JSONResponse:
    """Anthropic-envelope error with a real HTTP status."""
    return JSONResponse(
        status_code=status,
        content=error_envelope(error_type, message),
        headers=headers or None,
    )


def _mapped_response(mapped) -> JSONResponse:
    """Render a MappedError; its headers were already filtered and sanitised by the mapper."""
    return _error_response(mapped.status, mapped.error_type, mapped.message, mapped.headers)


def _exhausted_response() -> JSONResponse:
    """Our own 429 when every local key is over its RPM limit or cooling down."""
    retry_after = max(1, min(60, int(config.seconds_until_key_available())))
    return _error_response(
        429,
        "rate_limit_error",
        "All API keys exhausted. Please wait before trying again.",
        {"Retry-After": str(retry_after)},
    )


async def _prepend(first, gen):
    """Yield the already-read first chunk, then the rest of ``gen``; always close ``gen``."""
    try:
        yield first
        async for item in gen:
            yield item
    finally:
        await gen.aclose()


async def _empty():
    return
    yield  # pragma: no cover - makes this an async generator


async def _await_first_chunk(gen, http_request, client, request_id):
    """Read the first chunk of ``gen`` before any response byte is sent.

    The upstream call happens on the first ``__anext__``. Upstream failures re-raise unchanged
    (UpstreamError) and an empty stream raises StopAsyncIteration. There is no extra timer: a
    hang is bounded by the SDK's REQUEST_TIMEOUT, which surfaces as a mapped 500. While waiting,
    a client disconnect cancels the upstream call and raises _ClientGone.
    """
    task = asyncio.ensure_future(gen.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=FIRST_CHUNK_POLL_SECONDS)
            if done:
                return task.result()
            if await http_request.is_disconnected():
                client.cancel_request(request_id)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                await gen.aclose()
                client.active_requests.pop(request_id, None)
                raise _ClientGone()
    except BaseException:
        if not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - already unwinding; drop the task's outcome
                pass
        try:
            await gen.aclose()
        except BaseException:  # noqa: BLE001
            pass
        client.active_requests.pop(request_id, None)
        raise


@router.post("/v1/messages")
async def create_message(
    request: ClaudeMessagesRequest, http_request: Request, _: None = Depends(validate_api_key)
):
    request_id = str(uuid.uuid4())
    try:
        # Map Claude model to OpenAI model and tier
        openai_model, model_tier = model_manager.map_claude_model_to_openai(request.model)

        # Log incoming request with model info
        logger.info(
            "Request [%s] model=%s -> %s (tier=%s, stream=%s, reason=%s)",
            request_id[:8],
            request.model,
            openai_model,
            model_tier,
            request.stream,
            "auto-placeholder" if model_manager.is_auto_alias(request.model) else "tier-map",
        )

        # Content-free signal record (opt-in via AUTO_SIGNAL_LOG). Called once, above the
        # stream/non-stream split; runs inline because it is a no-op unless enabled.
        _emit_signal_safe(request, http_request)

        # Convert Claude request to OpenAI format
        openai_request = convert_claude_to_openai(request, model_manager)

        # Check if client disconnected before processing
        if await http_request.is_disconnected():
            raise HTTPException(status_code=499, detail="Client disconnected")

        # Get the model and tier from the model manager
        openai_model, model_tier = model_manager.map_claude_model_to_openai(request.model)
        # Update the OpenAI request with the resolved model
        openai_request["model"] = openai_model
        # Persist the actually-routed model (post-fallback) for the statusline.
        # Skip the "small" tier so the statusline keeps showing the last meaningful
        # (non-small) upstream model rather than the lightweight fallback.
        # Case-insensitive so "Small"/"SMALL" variants also skip the write.
        if (model_tier or "").lower() != "small":
            _write_last_model(model_tier or "unknown", openai_model)

        if request.stream:
            client = await config.get_next_client_async(stream=True)
            if client is None:
                return _exhausted_response()
            gen = client.create_chat_completion_stream(openai_request, request_id, model_tier)
            try:
                first = await _await_first_chunk(gen, http_request, client, request_id)
                stream_source = _prepend(first, gen)
            except StopAsyncIteration:
                stream_source = _empty()
            return StreamingResponse(
                convert_openai_streaming_to_claude_with_cancellation(
                    stream_source,
                    request,
                    logger,
                    http_request,
                    client,
                    request_id,
                ),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "*",
                },
            )

        # Non-streaming response
        client = await config.get_next_client_async()
        if client is None:
            return _exhausted_response()
        openai_response = await client.create_chat_completion(
            openai_request, request_id, model_tier
        )
        return convert_openai_to_claude_response(openai_response, request)
    except UpstreamError as e:
        # UpstreamHTTPError is also an HTTPException, so this must stay first. The client
        # already reported the failure to config, exactly once.
        logger.info(
            "Request [%s] failed: status=%s type=%s",
            request_id[:8],
            e.mapped.status,
            e.mapped.error_type,
        )
        return _mapped_response(e.mapped)
    except _ClientGone:
        logger.info("Request [%s] client disconnected before first chunk", request_id[:8])
        return _error_response(499, "api_error", "Client disconnected")
    except HTTPException as e:
        error_type = error_type_for_status(e.status_code)
        logger.info(
            "Request [%s] failed: status=%s type=%s", request_id[:8], e.status_code, error_type
        )
        return _error_response(e.status_code, error_type, str(e.detail), e.headers)
    except Exception:
        logger.error("Unexpected error processing request [%s]", request_id[:8])
        logger.error(traceback.format_exc())
        return _error_response(500, "api_error", "Internal server error")


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: ClaudeTokenCountRequest, _: None = Depends(validate_api_key)):
    try:
        # For token counting, we'll use a simple estimation
        # In a real implementation, you might want to use tiktoken or similar

        total_chars = 0

        # Count system message characters
        if request.system:
            if isinstance(request.system, str):
                total_chars += len(request.system)
            elif isinstance(request.system, list):
                for block in request.system:
                    if hasattr(block, "text"):
                        total_chars += len(block.text)

        # Count message characters
        for msg in request.messages:
            if msg.content is None:
                continue
            elif isinstance(msg.content, str):
                total_chars += len(msg.content)
            elif isinstance(msg.content, list):
                for block in msg.content:
                    if hasattr(block, "text") and block.text is not None:
                        total_chars += len(block.text)

        # Rough estimation: 4 characters per token
        estimated_tokens = max(1, total_chars // 4)

        return {"input_tokens": estimated_tokens}

    except Exception:
        # The exception text can echo request content or upstream detail; keep it in the server log only.
        logger.exception("Error counting tokens")
        raise HTTPException(status_code=500, detail="Token counting failed")


@router.get("/health")
async def health_check():
    """Health check endpoint with RPM info"""
    # Get current RPM stats
    now = time.time()
    rpm_info = []
    # Keys are identified by their 1-based position in OPENAI_API_KEY, never by any part of the
    # key itself: /health is unauthenticated, and even a prefix narrows a key.
    for key_index, (api_key, usage) in enumerate(config._provider_usage.items(), start=1):
        # Reset expired windows
        if now - usage["window_start"] >= 60:
            current_count = 0
        else:
            current_count = usage["count"]

        # Check penalty status
        penalty_remaining = 0
        if api_key in config._provider_penalties:
            penalty_remaining = max(0, config._provider_penalties[api_key] - now)

        rpm_info.append(
            {
                "key_index": key_index,
                "requests_this_minute": current_count,
                "rpm_limit": config._rpm_limit,
                "percentage_used": (
                    round((current_count / config._rpm_limit) * 100, 1)
                    if config._rpm_limit > 0
                    else 0
                ),
                "penalty_remaining_seconds": int(penalty_remaining),
                "window_age_seconds": int(now - usage["window_start"]),
            }
        )

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "openai_api_configured": bool(config.openai_api_key),
        "api_key_valid": config.validate_api_key(),
        "client_api_key_validation": bool(config.anthropic_api_key),
        "rpm_info": rpm_info,
        "total_configured_keys": len(config.providers),
    }


@router.get("/test-connection")
async def test_connection():
    """Test API connectivity to OpenAI"""
    try:
        # Simple test request to verify API connectivity
        client = await config.get_next_client_async()
        if client is None:
            raise RuntimeError("All API keys have reached their RPM limit or are under penalty.")
        test_response = await client.create_chat_completion(
            {
                "model": config.small_model,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 5,
            }
        )

        return {
            "status": "success",
            "message": "Successfully connected to OpenAI API",
            "model_used": config.small_model,
            "timestamp": datetime.now().isoformat(),
            "response_id": test_response.get("id", "unknown"),
        }

    except Exception as e:
        # Log the detail server-side only: upstream text can echo keys or request content.
        logger.error("API connectivity test failed: %s", type(e).__name__)
        return JSONResponse(
            status_code=503,
            content={
                "status": "failed",
                "error_type": "API Error",
                "message": "Upstream connectivity check failed; see the proxy log for the error type",
                "timestamp": datetime.now().isoformat(),
                "suggestions": [
                    "Check your OPENAI_API_KEY is valid",
                    "Verify your API key has the necessary permissions",
                    "Check if you have reached rate limits",
                ],
            },
        )


@router.get("/v1/models")
async def list_models():
    """List available models in Anthropic and OpenAI dual-compatible format.

    Exposes one alias per tier (opus/sonnet/haiku), plus an optional virtual auto
    alias (AUTO_MODEL_ALIAS) unless AUTO_MODEL_ENABLED is false. The alias the client
    picks is irrelevant for the tier aliases — model_manager routes it to the active
    model for that tier, as configured via BIG/MIDDLE/SMALL_MODEL in .env. The auto
    alias currently resolves to the BIG tier.
    """
    now_ts = int(time.time())
    now_iso = datetime.now().isoformat()

    # One representative per tier; .env tier mapping resolves the real model.
    claude_models = [
        {
            "id": "claude-3-opus-20240229",
            "display_name": "Opus (big tier)",
            "created_at": "2024-02-29T00:00:00Z",
            "created": 1709164800,
        },
        {
            "id": "claude-3-5-sonnet-20241022",
            "display_name": "Sonnet (middle tier)",
            "created_at": "2024-10-22T00:00:00Z",
            "created": 1729555200,
        },
        {
            "id": "claude-3-5-haiku-20241022",
            "display_name": "Haiku (small tier)",
            "created_at": "2024-10-22T00:00:00Z",
            "created": 1729555200,
        },
    ]

    if config.auto_model_enabled:
        claude_models.append(
            {
                "id": config.auto_model_alias,
                "display_name": "Auto (routes to big tier)",
                "created_at": "2025-01-01T00:00:00Z",
                "created": 1735689600,
            }
        )

    data = [
        {
            "id": m["id"],
            "type": "model",
            "object": "model",
            "display_name": m["display_name"],
            "created_at": m["created_at"],
            "created": m["created"],
            "owned_by": "claude-code-proxy",
        }
        for m in claude_models
    ]

    return {
        "object": "list",
        "data": data,
        "has_more": False,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
    }


@router.api_route("/api/hello", methods=["GET", "HEAD"])
@router.api_route("/hello", methods=["GET", "HEAD"])
async def api_hello():
    """Health probe endpoint used by Anthropic clients and Claude extensions."""
    return {"status": "ok"}


@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Claude-to-OpenAI API Proxy v1.0.0",
        "status": "running",
        "config": {
            "openai_base_url": config.openai_base_url,
            "max_tokens_limit": config.max_tokens_limit,
            "api_key_configured": bool(config.openai_api_key),
            "client_api_key_validation": bool(config.anthropic_api_key),
            "big_model": config.big_model,
            "small_model": config.small_model,
        },
        "endpoints": {
            "messages": "/v1/messages",
            "count_tokens": "/v1/messages/count_tokens",
            "models": "/v1/models",
            "health": "/health",
            "test_connection": "/test-connection",
        },
    }
