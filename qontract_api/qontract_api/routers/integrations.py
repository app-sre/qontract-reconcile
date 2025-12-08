"""Integrations router - aggregates all reconciliation integrations.

This router provides a dedicated namespace for all reconciliation integrations,
ensuring they are isolated under /integrations/* and can share common policies.
"""

from fastapi import APIRouter

from qontract_api.integrations.slack_usergroups import router as slack_usergroups_router
from qontract_api.integrations.slack_usergroups_v2 import (
    router as slack_usergroups_router_v2,
)

# Create integrations router
integrations_router = APIRouter(
    prefix="/integrations",
    tags=["integrations"],
)

# Include integration-specific routers
integrations_router.include_router(slack_usergroups_router.router)
integrations_router.include_router(slack_usergroups_router_v2.router)

# Future integrations will be added here:
# - AWS RDS reboot
# - GitHub workflows
# - etc.
