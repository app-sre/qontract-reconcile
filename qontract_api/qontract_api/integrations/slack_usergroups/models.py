"""Pydantic models for Slack usergroups reconciliation API."""

from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator

from qontract_api.models import TaskResult, TaskStatus
from qontract_api.slack.models import SlackWorkspace

_USERS_TRUNCATE_THRESHOLD = 30


def _truncate_users(users: list[str]) -> list[str]:
    """Truncate user list for serialization if it exceeds threshold."""
    if len(users) > _USERS_TRUNCATE_THRESHOLD:
        return [*users[:_USERS_TRUNCATE_THRESHOLD], "..."]
    return users


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

    @field_serializer("users")
    @classmethod
    def truncate_users(cls, users: list[str]) -> list[str]:
        """Truncate user list in serialized output to avoid huge log/event payloads."""
        return _truncate_users(users)


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

    @field_serializer("users")
    @classmethod
    def truncate_users(cls, users: list[str]) -> list[str]:
        """Truncate user list in serialized output to avoid huge log/event payloads."""
        return _truncate_users(users)


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


class SlackUsergroupsTaskResult(TaskResult, frozen=True):
    """Result model for completed reconciliation task.

    Returned by GET /reconcile/{task_id}.
    Contains the reconciliation results and execution status.
    """

    actions: list[SlackUsergroupAction] = Field(
        default=[],
        description="List of actions calculated/performed",
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
