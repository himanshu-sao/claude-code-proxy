import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import HTTPException
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai._exceptions import RateLimitError
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from src.core.config import config
from src.core.errors import (
    MappedError,
    UpstreamError,
    UpstreamHTTPError,
    counts_as_model_failure,
    map_upstream_error,
)

_log = logging.getLogger("client")


class OpenAIClient:
    """Async OpenAI client with cancellation support."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = 90,
        max_retries: int = 2,
        api_version: Optional[str] = None,
        custom_headers: Optional[Dict[str, str]] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_version = api_version
        self.custom_headers = custom_headers or {}
        self._last_model: Optional[str] = None
        self._last_model_tier: Optional[str] = None
        self.active_requests: Dict[str, asyncio.Event] = {}

        # Prepare default headers
        default_headers = {"Content-Type": "application/json", "User-Agent": "claude-proxy/1.0.0"}

        # Merge custom headers with default headers
        all_headers = {**default_headers, **self.custom_headers}

        # Detect if using Azure and instantiate the appropriate client
        if api_version:
            self.client = AsyncAzureOpenAI(
                api_key=api_key,
                azure_endpoint=base_url,
                api_version=api_version,
                timeout=timeout,
                max_retries=max_retries,
                default_headers=all_headers,
            )
        else:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
                default_headers=all_headers,
            )

    def _track_model(self, request: Dict[str, Any], tier: Optional[str] = None):
        """Record the model being used for this request."""
        self._last_model = request.get("model")
        self._last_model_tier = tier

    async def create_chat_completion(
        self,
        request: Dict[str, Any],
        request_id: Optional[str] = None,
        model_tier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send chat completion to OpenAI API with cancellation support."""
        self._track_model(request, model_tier)

        # Create cancellation token if request_id provided
        if request_id:
            cancel_event = asyncio.Event()
            self.active_requests[request_id] = cancel_event

        try:
            # Create task that can be cancelled
            completion_task = asyncio.create_task(self.client.chat.completions.create(**request))

            if request_id:
                # Wait for either completion or cancellation
                cancel_task = asyncio.create_task(cancel_event.wait())
                done, pending = await asyncio.wait(
                    [completion_task, cancel_task], return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # Check if request was cancelled
                if cancel_task in done:
                    completion_task.cancel()
                    raise HTTPException(status_code=499, detail="Request cancelled by client")

                completion = await completion_task
            else:
                completion = await completion_task

            # Convert to dict format that matches the original interface
            result = completion.model_dump()

            # Report successful model usage
            self.report_model_success()

            return result

        except HTTPException:
            raise
        except Exception as e:
            raise UpstreamHTTPError(self._handle_upstream_exception(e)) from e

        finally:
            # Clean up active request tracking
            if request_id and request_id in self.active_requests:
                del self.active_requests[request_id]

    async def create_chat_completion_stream(
        self,
        request: Dict[str, Any],
        request_id: Optional[str] = None,
        model_tier: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Send streaming chat completion to OpenAI API with cancellation support."""
        self._track_model(request, model_tier)

        # Create cancellation token if request_id provided
        if request_id:
            cancel_event = asyncio.Event()
            self.active_requests[request_id] = cancel_event

        try:
            # Ensure stream is enabled
            request["stream"] = True
            if "stream_options" not in request:
                request["stream_options"] = {}
            request["stream_options"]["include_usage"] = True

            # Create the streaming completion
            streaming_completion = await self.client.chat.completions.create(**request)

            async for chunk in streaming_completion:
                # Check for cancellation before yielding each chunk
                if request_id and request_id in self.active_requests:
                    if self.active_requests[request_id].is_set():
                        # Cancelled by the client: nothing to send to a closed connection
                        self._report_model_error(499, "Request cancelled")
                        return

                # Convert chunk to SSE format matching original HTTP client format
                chunk_dict = chunk.model_dump()
                chunk_json = json.dumps(chunk_dict, ensure_ascii=False)
                yield f"data: {chunk_json}"

            # Signal end of stream
            yield "data: [DONE]"

            # Report successful model usage (only if we got here without errors)
            self.report_model_success()

        except UpstreamError:
            raise
        except Exception as e:
            raise UpstreamError(self._handle_upstream_exception(e)) from e

        finally:
            # Clean up active request tracking
            if request_id and request_id in self.active_requests:
                del self.active_requests[request_id]

    def _handle_upstream_exception(self, exc: BaseException) -> MappedError:
        """Map an upstream failure and do the accounting (once per client call)."""
        mapped = map_upstream_error(exc, self.api_key)
        self._report_model_error(mapped.status, str(exc))
        if isinstance(exc, RateLimitError):
            config.report_rate_limit(self.api_key)
        return mapped

    def _redact(self, text: str) -> str:
        return text.replace(self.api_key, "[redacted]") if self.api_key else text

    def _report_model_error(self, status_code: int, error_detail: str):
        """Report model errors to config for fallback tracking."""
        if not self._last_model or not self._last_model_tier:
            return
        if self._last_model_tier == "unknown":
            return

        is_model_error = counts_as_model_failure(status_code, str(error_detail))

        # Log the error
        _log.warning(
            "Model error [%s] %s: %s (status=%d, model_error=%s)",
            self._last_model_tier.upper(),
            self._last_model,
            self._redact(str(error_detail))[:100],
            status_code,
            is_model_error,
        )

        if is_model_error:
            config.report_model_failure(self._last_model, self._last_model_tier)

    def report_model_success(self):
        """Report a successful model request."""
        if self._last_model and self._last_model_tier and self._last_model_tier != "unknown":
            _log.debug("Model success [%s] %s", self._last_model_tier.upper(), self._last_model)
            config.report_model_success(self._last_model, self._last_model_tier)

    def cancel_request(self, request_id: str) -> bool:
        """Cancel an active request by request_id."""
        if request_id in self.active_requests:
            self.active_requests[request_id].set()
            return True
        return False
