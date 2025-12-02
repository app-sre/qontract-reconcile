"""PagerDuty external API integration."""

from qontract_api.external.pagerduty.models import (
    EscalationPolicyUsersResponse,
    PagerDutyUser,
    ScheduleUsersResponse,
)
from qontract_api.external.pagerduty.pagerduty_factory import (
    create_pagerduty_workspace_client,
)

__all__ = [
    "EscalationPolicyUsersResponse",
    "PagerDutyUser",
    "ScheduleUsersResponse",
    "create_pagerduty_workspace_client",
]
