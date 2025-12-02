"""API models for PagerDuty external integration."""

from pydantic import BaseModel, ConfigDict, Field


class PagerDutyUser(BaseModel):
    """PagerDuty user representation.

    Immutable model representing a user from PagerDuty API.
    Username is the organization username (not PagerDuty email).

    Attributes:
        username: Organization username (mapped from org_username in internal models)
    """

    model_config = ConfigDict(frozen=True)

    username: str = Field(
        ...,
        description="Organization username (org_username)",
    )


class ScheduleUsersResponse(BaseModel):
    """Response model for schedule users endpoint.

    Immutable response containing list of users currently on-call in a schedule.

    Attributes:
        users: List of users currently on-call
    """

    model_config = ConfigDict(frozen=True)

    users: list[PagerDutyUser] = Field(
        default_factory=list,
        description="List of users currently on-call in the schedule",
    )


class EscalationPolicyUsersResponse(BaseModel):
    """Response model for escalation policy users endpoint.

    Immutable response containing list of users in an escalation policy.

    Attributes:
        users: List of users in escalation policy
    """

    model_config = ConfigDict(frozen=True)

    users: list[PagerDutyUser] = Field(
        default_factory=list,
        description="List of users in the escalation policy",
    )
