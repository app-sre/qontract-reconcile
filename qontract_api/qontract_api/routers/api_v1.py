"""API v1 router - aggregates all v1 endpoints.

This provides a central place for API versioning and allows
running multiple API versions in parallel (v1, v2, etc.).

Structure:
  /api/v1
    ├── /integrations/*  (reconciliation integrations)
    ├── /external/*      (external API endpoints - PagerDuty, GitHub, etc.)
    ├── /tasks/*         (task status/management - future)
    └── /utilities/*     (utility endpoints - future)
"""

from fastapi import APIRouter

from qontract_api.external.pagerduty import router as pagerduty_router
from qontract_api.external.vcs import router as vcs_router
from qontract_api.routers.integrations import integrations_router

# Create API v1 router
api_v1_router = APIRouter(prefix="/api/v1")

# Include major functional areas
api_v1_router.include_router(integrations_router)
api_v1_router.include_router(pagerduty_router.router)
api_v1_router.include_router(vcs_router.router)

# Future routers will be added here:
# - tasks_router for Celery task status/management
# - utilities_router for standalone utilities
