"""Health check utilities for qontract-api."""

from pydantic import BaseModel, Field

from qontract_api.config import settings
from qontract_api.dependencies import dependencies


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


async def check_cache_health() -> HealthStatus:
    """Check cache backend health."""
    if not dependencies.cache:
        return HealthStatus(status="unhealthy", message="Cache backend not initialized")

    try:
        is_healthy = await dependencies.cache.ping()
        if is_healthy:
            return HealthStatus(status="healthy", message="Cache backend reachable")
        return HealthStatus(status="unhealthy", message="Cache backend unreachable")
    except OSError as e:
        return HealthStatus(status="unhealthy", message=f"Cache check failed: {e}")


async def get_health_status() -> HealthResponse:
    """Get overall health status including all components."""
    components: dict[str, HealthStatus] = {}

    # Check cache
    cache_health = await check_cache_health()
    components["cache"] = cache_health

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
        service=settings.APP_NAME,
        version=settings.VERSION,
        components=components,
    )
