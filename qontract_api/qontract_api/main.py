"""qontract-api main FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse
from prometheus_fastapi_instrumentator import Instrumentator

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.exceptions import (
    APIError,
    api_error_handler,
    general_exception_handler,
    validation_exception_handler,
)
from qontract_api.health import HealthResponse, HealthResponseDep
from qontract_api.logger import setup_logging
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

    Initializes singletons:
    - CacheBackend (Redis/Valkey for distributed cache and rate limiting)
    - SecretBackend (Vault for secret management)
    """
    from qontract_api.cache.factory import get_cache  # noqa: PLC0415
    from qontract_api.secret_manager._factory import (  # noqa: PLC0415
        get_secret_manager,
    )

    # Startup: Initialize cache backend using factory (singleton pattern)
    _app.state.cache = get_cache()

    # Startup: Initialize secret backend using factory (singleton pattern)
    # This creates the Vault client connection and starts token auto-refresh thread
    _app.state.secret_manager = get_secret_manager(cache=_app.state.cache)

    yield

    # Cleanup secret backend on shutdown
    if hasattr(_app.state, "secret_manager") and _app.state.secret_manager is not None:
        _app.state.secret_manager.close()

    # Cleanup cache backend on shutdown
    if hasattr(_app.state, "cache") and _app.state.cache is not None:
        _app.state.cache.close()


setup_logging()

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


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Qontract API",
        version="1.0.0",
        summary="Qontract API OpenAPI schema",
        description="REST API for qontract-reconcile api integrations",
        routes=app.routes,
    )
    # get rid of the default Validation Error (422) response added by FastAPI
    # otherwise qontract-api-client lists them as possible responses for all endpoints ... very annoying!
    for path in openapi_schema["paths"].values():
        for operation in path.values():
            responses = operation.get("responses", {})
            if "422" in responses:
                del responses["422"]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


# See https://fastapi.tiangolo.com/how-to/extending-openapi/#override-the-method for details
app.openapi = custom_openapi  # type: ignore[method-assign]

# Add middleware (order matters - first added is outermost)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(GzipRequestMiddleware)  # Decompress gzip requests before parsing

# Include API version routers
app.include_router(api_v1_router)

Instrumentator(excluded_handlers=["/metrics", "/healthz"]).instrument(app).expose(
    app, include_in_schema=False
)


@app.get("/", include_in_schema=False, tags=["General"])
def root() -> Response:
    """Root endpoint - redirect to OpenAPI documentation."""
    return RedirectResponse(url="/docs")


@app.get("/health/live", operation_id="liveness", tags=["Health"])
def liveness() -> dict[str, str]:
    """Liveness probe - returns 200 if service is running."""
    return {
        "status": "healthy",
        "service": settings.app_name,
    }


@app.get("/health/ready", operation_id="readiness", tags=["Health"])
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
