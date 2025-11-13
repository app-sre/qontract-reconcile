"""qontract-api main FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from valkey.asyncio import Valkey

from qontract_api.cache import RedisCacheBackend
from qontract_api.config import settings
from qontract_api.dependencies import dependencies, get_current_user
from qontract_api.exceptions import (
    APIError,
    api_error_handler,
    general_exception_handler,
)
from qontract_api.health import HealthResponse, get_health_status
from qontract_api.middleware import RequestIDMiddleware, RequestLoggingMiddleware
from qontract_api.models import User


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle - startup and shutdown."""
    # Startup: Initialize cache backend
    if settings.CACHE_BACKEND == "redis":
        valkey_client = await Valkey.from_url(
            settings.CACHE_BROKER_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        dependencies.cache = RedisCacheBackend(valkey_client)
    else:
        msg = f"Unsupported cache backend: {settings.CACHE_BACKEND}"
        raise ValueError(msg)

    yield

    # Cleanup cache backend on shutdown
    if dependencies.cache:
        await dependencies.cache.close()


app = FastAPI(
    title=settings.APP_NAME,
    description="REST API for qontract reconciliation",
    version=settings.VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    # don't use add_exception_handler because of https://github.com/Kludex/starlette/discussions/2391
    exception_handlers={
        APIError: api_error_handler,
        Exception: general_exception_handler,
    },
)

# Add middleware (order matters - first added is outermost)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)


@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint - basic health check."""
    return {
        "message": "qontract-api is running",
        "status": "healthy",
        "version": settings.VERSION,
    }


@app.get("/health/live")
async def liveness() -> dict[str, str]:
    """Liveness probe - returns 200 if service is running."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
    }


@app.get("/health/ready")
async def readiness() -> HealthResponse:
    """Readiness probe - returns 200 if service is ready to accept requests."""
    return await get_health_status()


@app.get("/health")
async def health() -> HealthResponse:
    """Detailed health check including all components."""
    return await get_health_status()


@app.get("/api/protected")
async def protected_endpoint(
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """Protected endpoint - requires valid JWT token."""
    return {
        "message": "Access granted",
        "username": current_user.username,
    }
