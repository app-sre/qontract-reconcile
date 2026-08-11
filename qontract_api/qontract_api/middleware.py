"""Middleware for qontract-api."""

import contextlib
import gzip
import time
import uuid
import zlib
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect
from starlette.types import Receive

from qontract_api.auth import (
    decode_token,
)
from qontract_api.constants import (
    MAX_GZIP_COMPRESSED_SIZE,
    MAX_GZIP_DECOMPRESSED_SIZE,
    REQUEST_ID_HEADER,
)
from qontract_api.logger import get_logger

logger = get_logger(__name__)


class GzipCompressedSizeExceededError(Exception):
    """Raised when a gzip request body's compressed size exceeds the size limit."""

    def __init__(self, max_size: int) -> None:
        """Initialize with the exceeded size limit."""
        super().__init__(f"Compressed request body exceeds {max_size} bytes limit")


class GzipDecompressedSizeExceededError(Exception):
    """Raised when decompressing a gzip request body would exceed the size limit."""

    def __init__(self, max_size: int) -> None:
        """Initialize with the exceeded size limit."""
        super().__init__(f"Decompressed size exceeds {max_size} bytes")


async def _read_compressed_body(
    original_receive: Receive, max_compressed_size: int
) -> bytes:
    """Read chunks from the ASGI receive channel, bounding the total size.

    Rejects early (without buffering further chunks) once the total exceeds
    max_compressed_size, so an oversized upload can't exhaust memory even
    before decompression is attempted.
    """
    compressed_chunks: list[bytes] = []
    compressed_size = 0
    while True:
        message = await original_receive()
        if message["type"] == "http.disconnect":
            raise ClientDisconnect
        if message["type"] == "http.request":
            body_chunk = message.get("body", b"")
            if body_chunk:
                compressed_size += len(body_chunk)
                if compressed_size > max_compressed_size:
                    raise GzipCompressedSizeExceededError(max_compressed_size)
                compressed_chunks.append(body_chunk)
            if not message.get("more_body", False):
                break
    return b"".join(compressed_chunks)


def _decompress_gzip_bounded(
    compressed_body: bytes, max_decompressed_size: int
) -> bytes:
    """Decompress gzip data, aborting as soon as the output exceeds max_decompressed_size.

    Uses zlib's streaming API (rather than gzip.decompress()) so an oversized
    (gzip bomb) payload is rejected without fully materializing the decompressed
    output in memory. Like gzip.decompress(), concatenated gzip members are all
    decompressed; a stream that doesn't end with a complete member (truncated
    input) raises gzip.BadGzipFile instead of silently returning partial data.
    """
    output = bytearray()
    pending = compressed_body
    while pending:
        decompressor = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
        chunk = decompressor.decompress(
            pending, max_decompressed_size + 1 - len(output)
        )
        output.extend(chunk)
        if len(output) > max_decompressed_size:
            raise GzipDecompressedSizeExceededError(max_decompressed_size)
        while decompressor.unconsumed_tail:
            chunk = decompressor.decompress(
                decompressor.unconsumed_tail, max_decompressed_size + 1 - len(output)
            )
            output.extend(chunk)
            if len(output) > max_decompressed_size:
                raise GzipDecompressedSizeExceededError(max_decompressed_size)
        output.extend(decompressor.flush(max_decompressed_size + 1 - len(output)))
        if len(output) > max_decompressed_size:
            raise GzipDecompressedSizeExceededError(max_decompressed_size)
        if not decompressor.eof:
            raise gzip.BadGzipFile(
                "Compressed file ended before the end-of-stream marker was reached"
            )
        pending = decompressor.unused_data
    return bytes(output)


def _install_decompressed_body(
    request: Request, compressed_body: bytes, decompressed: bytes
) -> None:
    """Swap the request's receive channel to return the decompressed body and log details."""

    async def receive() -> dict[str, str | bytes | bool]:  # ruff: ignore[unused-async]
        return {
            "type": "http.request",
            "body": decompressed,
            "more_body": False,
        }

    request._receive = receive  # ruff: ignore[private-member-access]

    logger.debug(
        "Decompressed gzip request",
        compressed_size=len(compressed_body),
        decompressed_size=len(decompressed),
        compression_ratio=round((1 - len(compressed_body) / len(decompressed)) * 100, 1)
        if len(decompressed) > 0
        else 0,
        request_id=request.state.request_id,
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID to each request."""

    async def dispatch(  # ruff: ignore[no-self-use] - Required instance method for Starlette middleware
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request and add request ID."""
        # Generate server-side request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers[REQUEST_ID_HEADER] = request_id

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with timing information and structured fields."""

    async def dispatch(  # ruff: ignore[no-self-use] - Required instance method for Starlette middleware
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Process request and log details."""
        start_time = time.time()

        context_vars = {
            "request_id": request.state.request_id,
        } | {
            header.lower(): value
            for header, value in request.headers.items()
            if header.startswith("x-")
        }

        # dry_run from body if present
        with contextlib.suppress(Exception):
            json_body = await request.json()
            if isinstance(json_body, dict) and "dry_run" in json_body:
                context_vars["dry_run"] = json_body["dry_run"]

        # get username from authentication header if present
        if "authorization" in request.headers:
            with contextlib.suppress(Exception):
                auth_header = request.headers["authorization"]
                token_type, token = auth_header.split(" ")
                if token_type.lower() == "bearer":
                    # decode token to get username

                    payload = decode_token(token)
                    context_vars["username"] = payload.sub

        with structlog.contextvars.bound_contextvars(**context_vars):
            # Log request with structured fields
            logger.info(
                f"Start {request.method} {request.url.path}",
                http_method=request.method,
                http_path=str(request.url.path),
                client_host=request.client.host if request.client else None,
            )
            # Process request
            response = await call_next(request)

            # Calculate duration
            duration = time.time() - start_time

            # Log request with structured fields
            logger.info(
                f"Done {request.method} {request.url.path}",
                http_method=request.method,
                http_path=str(request.url.path),
                http_status=response.status_code,
                duration_seconds=round(duration, 3),
                client_host=request.client.host if request.client else None,
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

    async def dispatch(  # ruff: ignore[no-self-use] - Required instance method for Starlette middleware
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Decompress gzip request body if Content-Encoding header present."""
        if request.headers.get("content-encoding") == "gzip":
            try:
                original_receive = request._receive  # ruff: ignore[private-member-access]
                compressed_body = await _read_compressed_body(
                    original_receive, MAX_GZIP_COMPRESSED_SIZE
                )
                decompressed = _decompress_gzip_bounded(
                    compressed_body, MAX_GZIP_DECOMPRESSED_SIZE
                )
                _install_decompressed_body(request, compressed_body, decompressed)
            except ClientDisconnect:
                # Client is gone; propagate so no response is wasted building one.
                raise
            except GzipCompressedSizeExceededError as e:
                logger.warning(
                    "Compressed gzip request exceeds size limit",
                    max_compressed_size=MAX_GZIP_COMPRESSED_SIZE,
                    request_id=request.state.request_id,
                )
                return Response(
                    content=str(e), status_code=status.HTTP_413_CONTENT_TOO_LARGE
                )
            except GzipDecompressedSizeExceededError as e:
                logger.warning(
                    "Decompressed gzip request exceeds size limit",
                    max_decompressed_size=MAX_GZIP_DECOMPRESSED_SIZE,
                    request_id=request.state.request_id,
                )
                return Response(
                    content=str(e), status_code=status.HTTP_413_CONTENT_TOO_LARGE
                )
            except (gzip.BadGzipFile, zlib.error) as e:
                logger.exception(
                    "Failed to decompress gzip request",
                    request_id=request.state.request_id,
                )
                return Response(
                    content=f"Invalid gzip data: {e}",
                    status_code=400,
                )
            except Exception as e:
                logger.exception(
                    "Unexpected error decompressing request",
                    request_id=request.state.request_id,
                )
                return Response(
                    content=f"Failed to decompress request: {e}",
                    status_code=500,
                )

        return await call_next(request)
