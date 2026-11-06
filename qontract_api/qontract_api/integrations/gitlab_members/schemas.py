"""Pydantic schemas for GitLab members reconciliation API."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field
from qontract_utils.gitlab_api import GitlabAccessLevel

from qontract_api.integrations.gitlab_members.domain import GitlabMembersInstanceConfig
from qontract_api.models import TaskResult, TaskStatus


class GitlabMembersReconcileRequest(BaseModel, frozen=True):
    """Request model for GitLab members reconciliation."""

    instances: list[GitlabMembersInstanceConfig] = Field(
        ..., description="List of GitLab instances to reconcile"
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class GitlabMemberActionAdd(BaseModel, frozen=True):
    """Action: Add a user to a group."""

    action_type: Literal["add_member"] = "add_member"
    instance: str
    group: str
    username: str
    user_id: int
    access_level: GitlabAccessLevel


class GitlabMemberActionRemove(BaseModel, frozen=True):
    """Action: Remove a user from a group."""

    action_type: Literal["remove_member"] = "remove_member"
    instance: str
    group: str
    username: str
    member_id: int


class GitlabMemberActionChangeAccess(BaseModel, frozen=True):
    """Action: Change a member's access level."""

    action_type: Literal["change_access"] = "change_access"
    instance: str
    group: str
    username: str
    member_id: int
    access_level: GitlabAccessLevel


# Union type for all action models. Use GitlabMemberAction (not a specific
# action class) in all result fields so adding a future action type is a
# non-breaking schema extension.
GitlabMemberAction = Annotated[
    GitlabMemberActionAdd | GitlabMemberActionRemove | GitlabMemberActionChangeAccess,
    Field(discriminator="action_type"),
]


class GitlabMembersTaskResult(TaskResult, frozen=True):
    """Result of a completed reconciliation task."""

    actions: list[GitlabMemberAction] = Field(
        default_factory=list,
        description="All actions calculated (desired - current), including any that failed to apply.",
    )
    applied_actions: list[GitlabMemberAction] = Field(
        default_factory=list,
        description="Actions successfully applied (non-dry-run only).",
    )


class GitlabMembersTaskResponse(BaseModel, frozen=True):
    """Immediate response returned when the reconciliation task is queued."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    status_url: str = Field(..., description="URL to poll for task result")


class GitlabMembersErrorEvent(BaseModel, frozen=True):
    """Payload published when a reconciliation error is recorded."""

    error: str = Field(
        ..., description="The error message recorded during reconciliation."
    )
