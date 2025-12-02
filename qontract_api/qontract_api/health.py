"""Health check utilities for qontract-api."""

from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from qontract_api.cache.base import CacheBackend
from qontract_api.config import settings


class HealthStatus(BaseModel):
    """Health status for a component."""

    status: str = Field(..., description="Health status: healthy, unhealthy, degraded")
    message: str | None = Field(None, description="Optional status message")


class HealthResponse(BaseModel):
    """Overall health check response."""

    status: str = Field(..., description="Overall status: healthy, unhealthy, degraded")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    components: dict[str, HealthStatus] = Field(
        default_factory=dict, description="Component health statuses"
    )


def get_cache_from_request(request: Request) -> CacheBackend | None:
    """Get cache from app state, return None if not available.

    This is different from the get_cache() dependency which raises HTTPException.
    Health checks should not fail with 503, but report component status instead.
    """
    return getattr(request.app.state, "cache", None)


# Type alias for dependency injection
CacheOptionalDep = Annotated[CacheBackend | None, Depends(get_cache_from_request)]


def check_cache_health(cache: CacheBackend | None) -> HealthStatus:
    """Check cache backend health.

    Args:
        cache: Cache backend instance or None

    Returns:
        HealthStatus with current cache health
    """
    if not cache:
        return HealthStatus(status="unhealthy", message="Cache backend not initialized")

    try:
        if cache.ping():
            return HealthStatus(status="healthy", message="Cache backend reachable")
        return HealthStatus(status="unhealthy", message="Cache backend unreachable")
    except OSError as e:
        return HealthStatus(status="unhealthy", message=f"Cache check failed: {e}")


def check_worker_health() -> HealthStatus:
    """Check background worker health.

    Returns:
        HealthStatus with
          current cache health
    """
    # avoid circular imports
    from qontract_api.tasks.health import health_check  # noqa: PLC0415

    try:
        return health_check.delay().wait(timeout=5)
    except Exception as e:  # noqa: BLE001
        return HealthStatus(status="unhealthy", message=f"Worker check failed: {e}")


def get_health_status(cache: CacheOptionalDep) -> HealthResponse:
    """Get overall health status including all components.

    Args:
        cache: Cache backend from dependency injection

    Returns:
        HealthResponse with overall and component health
    """
    components: dict[str, HealthStatus] = {}

    # Check cache
    components["cache"] = check_cache_health(cache)
    components["worker"] = check_worker_health()

    # Determine overall status
    component_statuses = [c.status for c in components.values()]
    if all(s == "healthy" for s in component_statuses):
        overall_status = "healthy"
    elif any(s == "unhealthy" for s in component_statuses):
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status,
        service=settings.app_name,
        version=settings.version,
        components=components,
    )


# Type alias for dependency injection (must be after function definition)
HealthResponseDep = Annotated[HealthResponse, Depends(get_health_status)]
