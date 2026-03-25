"""Pydantic schemas for the github-owners reconciliation API.

Defines the API contract: request models, action models, task result, and
task response. All models are immutable (frozen=True) per ADR-012.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.github_owners.domain import GithubOrgDesiredState
from qontract_api.models import TaskResult, TaskStatus


class GithubOwnerActionAddOwner(BaseModel, frozen=True):
    """Action: Add a user as an org admin (owner).

    Note: Owner removal is intentionally NOT supported. The integration only
    adds owners and never removes them, preserving the behavior of the original
    github-owners reconcile integration. This is a deliberate safety decision —
    removing org admins is a high-impact operation that requires explicit manual
    review rather than automated removal.
    """

    action_type: Literal["add_owner"] = "add_owner"
    org_name: str = Field(..., description="GitHub organization name")
    username: str = Field(..., description="GitHub username to add as org admin")


# Union type for all action models (extensible for future action types).
# Use GithubOwnerAction (not GithubOwnerActionAddOwner directly) in all result
# fields so that adding a second action type is a non-breaking schema extension.
GithubOwnerAction = Annotated[
    GithubOwnerActionAddOwner,
    Field(discriminator="action_type"),
]


class GithubOwnersTaskResult(TaskResult, frozen=True):
    """Result model for a completed github-owners reconciliation task.

    Returned by GET /reconcile/{task_id}.
    """

    actions: list[GithubOwnerAction] = Field(
        default=[],
        description="All actions calculated (desired - current), including any that failed to apply.",
    )
    applied_actions: list[GithubOwnerAction] = Field(
        default=[],
        description="Actions that were successfully applied (non-dry-run only).",
    )


class GithubOwnersReconcileRequest(BaseModel, frozen=True):
    """Request model for github-owners reconciliation.

    POST requests always queue a background task and return immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.
    """

    organizations: list[GithubOrgDesiredState] = Field(
        ...,
        description="List of GitHub organizations with their desired owner membership",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class GithubOwnersTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile endpoint.

    Returned immediately when the task is queued. Contains task_id and
    status_url for retrieving the result via GET request.
    """

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )
