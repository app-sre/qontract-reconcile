"""API v1 router - aggregates all v1 endpoints.

This provides a central place for API versioning and allows
running multiple API versions in parallel (v1, v2, etc.).

Structure:
  /api/v1
    ├── /integrations/*  (reconciliation integrations)
    ├── /tasks/*         (task status/management - future)
    └── /utilities/*     (utility endpoints - future)
"""

from fastapi import APIRouter

from qontract_api.routers.integrations import integrations_router

# Create API v1 router
api_v1_router = APIRouter(prefix="/api/v1")

# Include major functional areas
api_v1_router.include_router(integrations_router)

# Future routers will be added here:
# - tasks_router for Celery task status/management
# - utilities_router for standalone utilities
