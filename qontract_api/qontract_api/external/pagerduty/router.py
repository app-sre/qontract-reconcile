"""FastAPI router for PagerDuty external API endpoints.

Provides cached access to PagerDuty data (schedules, escalation policies).
"""

from typing import Annotated

from fastapi import APIRouter, Query

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep
from qontract_api.external.pagerduty.models import (
    EscalationPolicyUsersResponse,
    PagerDutyUser,
    ScheduleUsersResponse,
)
from qontract_api.external.pagerduty.pagerduty_factory import (
    create_pagerduty_workspace_client,
)
from qontract_api.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/pagerduty",
    tags=["external"],
)


@router.get(
    "/schedules/{schedule_id}/users",
    operation_id="pagerduty-schedule-users",
)
def get_schedule_users(
    schedule_id: str,
    instance: Annotated[
        str,
        Query(description="PagerDuty instance name (e.g., 'app-sre')"),
    ],
    cache: CacheDep,
    secret_manager: SecretManagerDep,
) -> ScheduleUsersResponse:
    """Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users (username is org_username)

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/schedules/ABC123/users?instance=app-sre
        Response:
        {
            "users": [
                {"username": "jsmith"},
                {"username": "mdoe"}
            ]
        }
    """
    logger.info(
        f"Fetching users for schedule {schedule_id}",
        extra={"schedule_id": schedule_id, "instance": instance},
    )

    client = create_pagerduty_workspace_client(
        instance_name=instance,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )
    users = client.get_schedule_users(schedule_id)

    logger.info(
        f"Found {len(users)} users in schedule {schedule_id}",
        extra={
            "schedule_id": schedule_id,
            "instance": instance,
            "user_count": len(users),
        },
    )

    return ScheduleUsersResponse(
        users=[PagerDutyUser(username=user.org_username) for user in users]
    )


@router.get(
    "/escalation-policies/{policy_id}/users",
    operation_id="pagerduty-escalation-policy-users",
)
def get_escalation_policy_users(
    policy_id: str,
    instance: Annotated[
        str,
        Query(description="PagerDuty instance name (e.g., 'app-sre')"),
    ],
    cache: CacheDep,
    secret_manager: SecretManagerDep,
) -> EscalationPolicyUsersResponse:
    """Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users (username is org_username)

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/escalation-policies/XYZ789/users?instance=app-sre
        Response:
        {
            "users": [
                {"username": "jsmith"},
                {"username": "mdoe"}
            ]
        }
    """
    logger.info(
        f"Fetching users for escalation policy {policy_id}",
        extra={"policy_id": policy_id, "instance": instance},
    )

    client = create_pagerduty_workspace_client(
        instance_name=instance,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )
    users = client.get_escalation_policy_users(policy_id)

    logger.info(
        f"Found {len(users)} users in escalation policy {policy_id}",
        extra={
            "policy_id": policy_id,
            "instance": instance,
            "user_count": len(users),
        },
    )

    return EscalationPolicyUsersResponse(
        users=[PagerDutyUser(username=user.org_username) for user in users]
    )
