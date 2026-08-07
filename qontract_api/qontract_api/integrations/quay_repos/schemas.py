"""Pydantic schemas for Quay repos reconciliation API."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from qontract_api.models import Secret, TaskResult, TaskStatus


class QuayOrgKey(BaseModel, frozen=True):
    """Identifies a Quay organization uniquely across instances."""

    instance: str = Field(..., description="Quay instance name (e.g. quay.io)")
    org_name: str = Field(..., description="Quay organization name")

    def lock_key(self) -> str:
        return f"{self.instance}/{self.org_name}"


class QuayRepoConfig(BaseModel, frozen=True):
    """Desired state for a single Quay repository."""

    name: str = Field(..., description="Repository name")
    public: bool = Field(..., description="Whether the repository should be public")
    description: str = Field(default="", description="Repository description")


class QuayOrgConfig(BaseModel, frozen=True):
    """Configuration for a single Quay organization to reconcile."""

    instance: str = Field(..., description="Quay instance name")
    org_name: str = Field(..., description="Quay organization name")
    base_url: str = Field(..., description="Quay instance base URL")
    automation_token: Secret = Field(..., description="Secret reference for API token")
    managed_repos: bool = Field(..., description="Whether repos are managed by app-interface")
    mirror: QuayOrgKey | None = Field(
        default=None, description="Upstream org this org mirrors (if any)"
    )
    repos: list[QuayRepoConfig] = Field(
        default_factory=list, description="Desired repository state for this org"
    )

    @field_validator("repos")
    @classmethod
    def repos_names_unique(cls, repos: list[QuayRepoConfig]) -> list[QuayRepoConfig]:
        names = [r.name for r in repos]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate repo names: {', '.join(sorted(duplicates))}")
        return repos

    @property
    def key(self) -> QuayOrgKey:
        return QuayOrgKey(instance=self.instance, org_name=self.org_name)


class QuayReposReconcileRequest(BaseModel, frozen=True):
    """Request model for Quay repos reconciliation."""

    orgs: list[QuayOrgConfig] = Field(
        ..., description="List of Quay organizations to reconcile"
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )




class QuayRepoActionCreate(BaseModel, frozen=True):
    """Action: Create a new repository."""

    action_type: Literal["create"] = "create"
    instance: str
    org_name: str
    repo_name: str
    public: bool
    description: str


class QuayRepoActionDelete(BaseModel, frozen=True):
    """Action: Delete a repository no longer in desired state."""

    action_type: Literal["delete"] = "delete"
    instance: str
    org_name: str
    repo_name: str


class QuayRepoActionUpdateDescription(BaseModel, frozen=True):
    """Action: Update repository description."""

    action_type: Literal["update_description"] = "update_description"
    instance: str
    org_name: str
    repo_name: str
    description: str


class QuayRepoActionUpdateVisibility(BaseModel, frozen=True):
    """Action: Update repository visibility (public/private)."""

    action_type: Literal["update_visibility"] = "update_visibility"
    instance: str
    org_name: str
    repo_name: str
    public: bool


QuayRepoAction = (
    QuayRepoActionCreate
    | QuayRepoActionDelete
    | QuayRepoActionUpdateDescription
    | QuayRepoActionUpdateVisibility
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class QuayReposTaskResult(TaskResult, frozen=True):
    """Result of a completed reconciliation task."""

    actions: list[QuayRepoAction] = Field(
        default_factory=list,
        description="All actions calculated (desired - current).",
    )
    applied_actions: list[QuayRepoAction] = Field(
        default_factory=list,
        description="Actions successfully applied (non-dry-run only).",
    )


class QuayReposTaskResponse(BaseModel, frozen=True):
    """Immediate response returned when the reconciliation task is queued."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    status_url: str = Field(..., description="URL to poll for task result")
