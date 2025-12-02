"""Middleware for qontract-api."""

import gzip
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from qontract_api.constants import REQUEST_ID_HEADER
from qontract_api.logger import get_logger, request_id_context

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to each request."""

    async def dispatch(  # noqa: PLR6301 - Required instance method for Starlette middleware
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request and add request ID."""
        # Generate server-side request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Set request ID in context for logging
        token = request_id_context.set(request_id)

        try:
            # Process request
            response = await call_next(request)

            # Add request ID to response headers
            response.headers[REQUEST_ID_HEADER] = request_id

            return response
        finally:
            # Reset context
            request_id_context.reset(token)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with timing information and structured fields."""

    async def dispatch(  # noqa: PLR6301 - Required instance method for Starlette middleware
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request and log details."""
        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log request with structured fields
        # request_id is automatically added by RequestIDFilter
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code} - {duration:.3f}s",
            extra={
                "http_method": request.method,
                "http_path": str(request.url.path),
                "http_status": response.status_code,
                "duration_seconds": round(duration, 3),
                "client_host": request.client.host if request.client else None,
            },
        )

        return response


class GzipRequestMiddleware(BaseHTTPMiddleware):
    """Decompress gzip-encoded request bodies.

    Detects requests with Content-Encoding: gzip header,
    decompresses the body transparently, and forwards to endpoint.

    This enables clients to send compressed payloads for large desired_state data,
    reducing network transfer size by ~99% (e.g., 291 KB → 3 KB).

    Usage:
        Client sets Content-Encoding: gzip header and sends gzip-compressed body.
        Middleware decompresses automatically before FastAPI parses the request.

    Note:
        Works on raw ASGI receive channel, before request.body() is called.
        This ensures FastAPI receives the decompressed body correctly.
    """

    async def dispatch(  # noqa: PLR6301 - Required instance method for Starlette middleware
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Decompress gzip request body if Content-Encoding header present."""
        if request.headers.get("content-encoding") == "gzip":
            try:
                # Read all chunks from original receive
                compressed_chunks: list[bytes] = []
                original_receive = request._receive  # noqa: SLF001

                while True:
                    message = await original_receive()
                    if message["type"] == "http.request":
                        body_chunk = message.get("body", b"")
                        if body_chunk:
                            compressed_chunks.append(body_chunk)
                        if not message.get("more_body", False):
                            break

                # Concatenate and decompress
                compressed_body = b"".join(compressed_chunks)
                decompressed = gzip.decompress(compressed_body)

                # Create new receive that returns decompressed body
                async def receive() -> dict[str, str | bytes | bool]:  # noqa: RUF029
                    return {
                        "type": "http.request",
                        "body": decompressed,
                        "more_body": False,
                    }

                request._receive = receive  # noqa: SLF001

                logger.debug(
                    "Decompressed gzip request",
                    extra={
                        "compressed_size": len(compressed_body),
                        "decompressed_size": len(decompressed),
                        "compression_ratio": round(
                            (1 - len(compressed_body) / len(decompressed)) * 100, 1
                        )
                        if len(decompressed) > 0
                        else 0,
                    },
                )
            except gzip.BadGzipFile as e:
                logger.exception(
                    "Failed to decompress gzip request",
                    extra={"error": str(e)},
                )
                return Response(
                    content=f"Invalid gzip data: {e}",
                    status_code=400,
                )
            except Exception as e:
                logger.exception(
                    "Unexpected error decompressing request",
                    extra={"error": str(e)},
                )
                return Response(
                    content=f"Failed to decompress request: {e}",
                    status_code=500,
                )

        return await call_next(request)
