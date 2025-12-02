"""Pydantic models for Slack usergroups reconciliation API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import TaskStatus


class SlackUsergroupConfig(BaseModel, frozen=True):
    """Desired state configuration for a single Slack usergroup."""

    description: str = Field("", description="Usergroup description")
    users: list[str] = Field(
        [],
        description="List of user emails (e.g., user@example.com)",
    )
    channels: list[str] = Field(
        [],
        description="List of channel names (e.g., #general, team-channel)",
    )

    @field_validator("users", "channels", mode="after")
    @classmethod
    def sorted_list(cls, value: list[str]) -> list[str]:
        return sorted(value)


class SlackUsergroup(BaseModel, frozen=True):
    """A single Slack usergroup with its handle and configuration."""

    handle: str = Field(..., description="Usergroup handle/name (unique identifier)")
    config: SlackUsergroupConfig = Field(..., description="Usergroup configuration")


class SlackWorkspace(BaseModel, frozen=True):
    """A Slack workspace with its token and usergroups."""

    name: str = Field(..., description="Workspace name (unique identifier)")
    usergroups: list[SlackUsergroup] = Field(
        ..., description="List of usergroups in this workspace"
    )
    managed_usergroups: list[str] = Field(
        ...,
        description="This list shows the usergroup handles/names managed by qontract-api. Any user group not included here will be abandoned during reconciliation.",
    )


class SlackUsergroupsReconcileRequest(BaseModel, frozen=True):
    """Request model for Slack usergroups reconciliation.

    POST requests always queue a background task (async execution).
    """

    workspaces: list[SlackWorkspace] = Field(
        ..., description="List of Slack workspaces with their usergroups"
    )
    dry_run: bool = Field(
        default=True,  # CRITICAL: Default TRUE for safety!
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


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
