"""Pydantic schemas for GitLab projects reconciliation API."""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import Secret, TaskResult, TaskStatus


class GitlabProjectConfig(BaseModel, frozen=True):
    """Desired state for a single GitLab project."""

    name: str = Field(..., description="Project name")
    is_saas_bundle: bool = Field(
        default=False,
        description=(
            "Whether this project should be initialized as a SaaS bundle repo "
            "(README + staging/production branches) rather than left empty"
        ),
    )


class GitlabGroupConfig(BaseModel, frozen=True):
    """Configuration for a single GitLab group and its desired projects."""

    group: str = Field(..., description="GitLab group full path")
    projects: list[GitlabProjectConfig] = Field(
        default_factory=list, description="Desired projects under this group"
    )

    @field_validator("projects")
    @classmethod
    def project_names_unique(
        cls, projects: list[GitlabProjectConfig]
    ) -> list[GitlabProjectConfig]:
        duplicate_counter = Counter(project.name for project in projects)
        duplicates = {name for name, count in duplicate_counter.items() if count > 1}
        if duplicates:
            raise ValueError(
                f"duplicate project names: {', '.join(sorted(duplicates))}"
            )
        return projects


class GitlabInstanceConfig(BaseModel, frozen=True):
    """Configuration for a single GitLab instance to reconcile."""

    name: str = Field(..., description="GitLab instance name")
    url: str = Field(..., description="GitLab instance URL")
    ssl_verify: bool = Field(
        default=True, description="Whether to verify SSL certificates"
    )
    token: Secret = Field(..., description="Secret reference for the instance token")
    groups: list[GitlabGroupConfig] = Field(
        default_factory=list, description="Desired group/project state"
    )

    def lock_key(self) -> str:
        return self.name


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
