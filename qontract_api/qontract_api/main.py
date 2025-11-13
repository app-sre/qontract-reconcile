"""qontract-api main FastAPI application."""

from typing import Any

from fastapi import FastAPI

from qontract_api.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description="REST API for qontract reconciliation",
    version=settings.VERSION,
    debug=settings.DEBUG,
)


@app.get("/")
async def root() -> dict[str, Any]:
    """Root endpoint - basic health check."""
    return {
        "message": "qontract-api is running",
        "status": "healthy",
        "version": settings.VERSION,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for liveness probes."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.VERSION,
    }
