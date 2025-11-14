"""Pydantic models for Slack usergroups reconciliation API."""

from typing import Literal

from pydantic import BaseModel, Field

from qontract_api.models import TaskStatus


class SlackUsergroupConfig(BaseModel, frozen=True):
    """Desired state configuration for a single Slack usergroup."""

    description: str = Field("", description="Usergroup description")
    users: frozenset[str] = Field(
        default_factory=frozenset,
        description="List of user emails (e.g., user@example.com)",
    )
    channels: frozenset[str] = Field(
        default_factory=frozenset,
        description="List of channel names (e.g., #general, team-channel)",
    )


class SlackUsergroup(BaseModel, frozen=True):
    """A single Slack usergroup with its handle and configuration."""

    handle: str = Field(..., description="Usergroup handle/name (unique identifier)")
    config: SlackUsergroupConfig = Field(..., description="Usergroup configuration")


class SlackWorkspace(BaseModel, frozen=True):
    """A Slack workspace with its token and usergroups."""

    name: str = Field(..., description="Workspace name (unique identifier)")
    vault_token_path: str = Field(
        ...,
        description="Vault path to Slack workspace token (e.g., 'app-sre/integrations-output/slack-workspace-1/token')",
    )
    usergroups: frozenset[SlackUsergroup] = Field(
        ..., description="List of usergroups in this workspace"
    )
    managed_usergroups: list[str] = Field(
        ...,
        description="This list shows the usergroup handles/names managed by qontract-api. Any user group not included here will be abandoned during reconciliation.",
    )


class SlackUsergroupsReconcileRequest(BaseModel, frozen=True):
    """Request model for Slack usergroups reconciliation.

    POST requests always queue a background task (async execution).
    See ADR-003 for rationale: docs/adr/ADR-003-async-only-api-with-blocking-get.md
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
    workspace: str = Field(..., description="Slack workspace name")
    usergroup: str = Field(..., description="Usergroup handle/name")
    users: list[str] = Field([], description="Users to add to usergroup")
    description: str = Field(..., description="New description")


class SlackUsergroupActionUpdateUsers(BaseModel, frozen=True):
    """Action: Update usergroup users."""

    action_type: Literal["update_users"] = "update_users"
    workspace: str = Field(..., description="Slack workspace name")
    usergroup: str = Field(..., description="Usergroup handle/name")
    users: list[str] = Field([], description="Lst of users for usergroup")


class SlackUsergroupActionUpdateMetadata(BaseModel, frozen=True):
    """Action: Update usergroup channels."""

    action_type: Literal["update_metadata"] = "update_metadata"
    workspace: str = Field(..., description="Slack workspace name")
    usergroup: str = Field(..., description="Usergroup handle/name")
    description: str = Field(..., description="New description")
    channels: list[str] = Field([], description="Lst of channels for usergroup")


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

    task_id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )
