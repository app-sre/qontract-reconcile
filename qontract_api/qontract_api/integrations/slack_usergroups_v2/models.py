"""Pydantic models for Slack usergroups reconciliation API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import TaskStatus


class UserSourceOrgUsernames(BaseModel, frozen=True):
    provider: Literal["org_usernames"] = "org_usernames"
    org_usernames: list[str]


class UserSourceGitOwners(BaseModel, frozen=True):
    provider: Literal["git_owners"] = "git_owners"
    git_url: str


class UserSourcePagerDuty(BaseModel, frozen=True):
    provider: Literal["pagerduty"] = "pagerduty"
    instance_name: str
    schedule_id: str | None
    escalation_policy_id: str | None


class SlackUsergroupRequest(BaseModel, frozen=True):
    """A single Slack usergroup with its handle and configuration."""

    handle: str = Field(..., description="Usergroup handle/name (unique identifier)")
    description: str = Field("", description="Usergroup description")
    user_sources: list[
        UserSourceOrgUsernames | UserSourceGitOwners | UserSourcePagerDuty
    ] = Field(
        [],
        description="List of user sources for this usergroup",
    )
    channels: list[str] = Field(
        [],
        description="List of channel names (e.g., #general, team-channel)",
    )


class SlackWorkspaceRequest(BaseModel, frozen=True):
    """A Slack workspace with its token and usergroups."""

    name: str = Field(..., description="Workspace name (unique identifier)")
    usergroups: list[SlackUsergroupRequest] = Field(
        ..., description="List of usergroups in this workspace"
    )
    managed_usergroups: list[str] = Field(
        ...,
        description="This list shows the usergroup handles/names managed by qontract-api. Any user group not included here will be abandoned during reconciliation.",
    )


class SlackUsergroupsUser(BaseModel, frozen=True):
    org_username: str
    github_username: str | None
    pagerduty_username: str | None
    tag_on_merge_requests: bool | None


class SlackUsergroupsReconcilePayload(BaseModel, frozen=True):
    workspaces: list[SlackWorkspaceRequest] = Field(
        ..., description="List of Slack workspaces with their usergroups"
    )
    users: list[SlackUsergroupsUser]


class SlackUsergroupsReconcileRequestV2(BaseModel, frozen=True):
    """Request model for Slack usergroups reconciliation.

    POST requests always queue a background task (async execution).
    """

    payload: SlackUsergroupsReconcilePayload = Field(
        ..., description="Reconciliation payload with workspaces and users"
    )
    dry_run: bool = Field(
        default=True,  # CRITICAL: Default TRUE for safety!
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class SlackUsergroup(BaseModel, frozen=True):
    """A single Slack usergroup."""

    handle: str = Field(..., description="Usergroup handle/name (unique identifier)")
    description: str = Field("", description="Usergroup description")
    users: list[str] = Field(
        [],
        description="List of user org_usernames (e.g., user1, user2)",
    )
    channels: list[str] = Field(
        [],
        description="List of channel names (e.g., #general, team-channel)",
    )

    @field_validator("users", "channels", mode="after")
    @classmethod
    def sorted_list(cls, value: list[str]) -> list[str]:
        return sorted(value)


# Type-safe action models
class SlackUsergroupActionCreate(BaseModel, frozen=True):
    """Action: Create a new usergroup."""

    action_type: Literal["create"] = "create"
    workspace: str = Field(..., description="Workspace name")
    usergroup: str = Field(..., description="Usergroup handle/name")
    users: list[str] = Field(..., description="List of users to add")
    description: str = Field(..., description="Usergroup description")

    @field_validator("users", mode="after")
    @classmethod
    def sorted_list(cls, value: list[str]) -> list[str]:
        return sorted(value)


class SlackUsergroupActionUpdateUsers(BaseModel, frozen=True):
    """Action: Update usergroup users."""

    action_type: Literal["update_users"] = "update_users"
    workspace: str = Field(..., description="Workspace name")
    usergroup: str = Field(..., description="Usergroup handle/name")
    users: list[str] = Field(..., description="List of users after update")
    users_to_add: list[str] = Field(..., description="List of users to add")
    users_to_remove: list[str] = Field(..., description="List of users to remove")

    @field_validator("users", mode="after")
    @classmethod
    def sorted_list(cls, value: list[str]) -> list[str]:
        return sorted(value)


class SlackUsergroupActionUpdateMetadata(BaseModel, frozen=True):
    """Action: Update usergroup channels."""

    action_type: Literal["update_metadata"] = "update_metadata"
    workspace: str = Field(..., description="Workspace name")
    usergroup: str = Field(..., description="Usergroup handle/name")
    description: str = Field(..., description="Usergroup description")
    channels: list[str] = Field(..., description="Usergroup channels")

    @field_validator("channels", mode="after")
    @classmethod
    def sorted_list(cls, value: list[str]) -> list[str]:
        return sorted(value)


# Union type for all actions
SlackUsergroupAction = (
    SlackUsergroupActionCreate
    | SlackUsergroupActionUpdateUsers
    | SlackUsergroupActionUpdateMetadata
)


class SlackUsergroupsTaskResult(BaseModel, frozen=True):
    """Result model for completed reconciliation task.

    Returned by GET /reconcile/{task_id}.
    Contains the reconciliation results and execution status.
    """

    status: TaskStatus = Field(
        ...,
        description="Task execution status (pending/success/failed)",
    )
    actions: list[SlackUsergroupAction] = Field(
        [],
        description="List of actions calculated/performed",
    )
    applied_count: int = Field(
        default=0,
        description="Number of actions actually applied (0 if dry_run=True)",
    )
    errors: list[str] | None = Field(
        default=None,
        description="List of errors encountered during reconciliation",
    )


class SlackUsergroupsTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile endpoint.

    Returned immediately when task is queued. Contains task_id and status_url
    for retrieving the result via GET request.
    """

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )
