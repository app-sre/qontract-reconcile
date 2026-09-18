"""Pydantic schemas for GitLab projects reconciliation API."""

from typing import Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.gitlab_projects.domain import GitlabInstanceConfig
from qontract_api.models import TaskResult, TaskStatus


class GitlabProjectsReconcileRequest(BaseModel, frozen=True):
    """Request model for GitLab projects reconciliation."""

    instances: list[GitlabInstanceConfig] = Field(
        ..., description="List of GitLab instances to reconcile"
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class GitlabProjectActionCreate(BaseModel, frozen=True):
    """Action: Create a new, empty project."""

    action_type: Literal["create"] = "create"
    instance: str
    group: str
    project_name: str


class GitlabProjectActionCreateSaasBundle(BaseModel, frozen=True):
    """Action: Create a new project and initialize it as a SaaS bundle repo."""

    action_type: Literal["create_saas_bundle"] = "create_saas_bundle"
    instance: str
    group: str
    project_name: str


GitlabProjectAction = GitlabProjectActionCreate | GitlabProjectActionCreateSaasBundle


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class GitlabProjectsTaskResult(TaskResult, frozen=True):
    """Result of a completed reconciliation task."""

    actions: list[GitlabProjectAction] = Field(
        default_factory=list,
        description="All actions calculated (desired - current).",
    )
    applied_actions: list[GitlabProjectAction] = Field(
        default_factory=list,
        description="Actions successfully applied (non-dry-run only).",
    )


class GitlabProjectsTaskResponse(BaseModel, frozen=True):
    """Immediate response returned when the reconciliation task is queued."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    status_url: str = Field(..., description="URL to poll for task result")


# ---------------------------------------------------------------------------
# Error models
# ---------------------------------------------------------------------------


class GitlabProjectsErrorEvent(BaseModel, frozen=True):
    """Payload published when a reconciliation error is recorded."""

    error: str = Field(
        ..., description="The error message recorded during reconciliation."
    )
