"""qontract-api main FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from valkey import Valkey

from qontract_api.cache import RedisCacheBackend
from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.exceptions import (
    APIError,
    api_error_handler,
    general_exception_handler,
    validation_exception_handler,
)
from qontract_api.health import HealthResponse, HealthResponseDep
from qontract_api.middleware import (
    GzipRequestMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
)
from qontract_api.routers.api_v1 import api_v1_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: RUF029
    """Manage application lifecycle - startup and shutdown.

    Note: FastAPI requires async lifespan, but our code is sync.
    The sync operations run in the event loop without blocking.
    """
    # Startup: Initialize cache backend with two-tier caching (sync operations)
    if settings.cache_backend == "redis":
        valkey_client = Valkey.from_url(
            settings.cache_broker_url,
            encoding="utf-8",
            decode_responses=True,
        )
        _app.state.cache = RedisCacheBackend(
            valkey_client,
            memory_max_size=settings.cache_memory_max_size,
            memory_ttl=settings.cache_memory_ttl,
        )
    else:
        msg = f"Unsupported cache backend: {settings.cache_backend}"
        raise ValueError(msg)

    yield

    # Cleanup cache backend on shutdown (sync operation)
    if hasattr(_app.state, "cache") and _app.state.cache is not None:
        _app.state.cache.close()


app = FastAPI(
    title=settings.app_name,
    description="REST API for qontract reconciliation",
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
    openapi_url="/docs/openapi.json",
    # don't use add_exception_handler because of https://github.com/Kludex/starlette/discussions/2391
    exception_handlers={
        APIError: api_error_handler,
        Exception: general_exception_handler,
        RequestValidationError: validation_exception_handler,
    },
)

# Add middleware (order matters - first added is outermost)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(GzipRequestMiddleware)  # Decompress gzip requests before parsing

# Include API version routers
app.include_router(api_v1_router)


@app.get("/", operation_id="check", tags=["General"])
def root() -> Response:
    """Root endpoint - redirect to OpenAPI documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health/live", include_in_schema=False, tags=["General"])
def liveness() -> dict[str, str]:
    """Liveness probe - returns 200 if service is running."""
    return {
        "status": "healthy",
        "service": settings.app_name,
    }


@app.get("/health/ready", include_in_schema=False, tags=["General"])
def readiness(health_status: HealthResponseDep) -> HealthResponse:
    """Readiness probe - returns 200 if service is ready to accept requests."""
    return health_status


@app.get("/api/protected", include_in_schema=False)
def protected_endpoint(current_user: UserDep) -> dict[str, str]:
    """Protected endpoint - requires valid JWT token."""
    return {
        "message": "Access granted",
        "username": current_user.username,
    }
