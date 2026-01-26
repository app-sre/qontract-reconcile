"""Integrations router - aggregates all reconciliation integrations.

This router provides a dedicated namespace for all reconciliation integrations,
ensuring they are isolated under /integrations/* and can share common policies.
"""

from fastapi import APIRouter

from qontract_api.integrations.slack_usergroups import router as slack_usergroups_router

# Create integrations router
integrations_router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
)

# Include integration-specific routers
integrations_router.include_router(slack_usergroups_router.router)

# Future integrations will be added here:
# - AWS RDS reboot
# - GitHub workflows
# - etc.
