"""Pydantic schemas for Glitchtip reconciliation API."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.glitchtip.domain import GIInstance
from qontract_api.models import TaskResult, TaskStatus

# --- 14 action models (discriminated union) ---


class GlitchtipActionCreateOrganization(BaseModel, frozen=True):
    """Action: Create a new organization."""

    action_type: Literal["create_organization"] = "create_organization"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")


class GlitchtipActionDeleteOrganization(BaseModel, frozen=True):
    """Action: Delete an organization."""

    action_type: Literal["delete_organization"] = "delete_organization"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")


class GlitchtipActionInviteUser(BaseModel, frozen=True):
    """Action: Invite a user to an organization."""

    action_type: Literal["invite_user"] = "invite_user"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="Organization role")


class GlitchtipActionDeleteUser(BaseModel, frozen=True):
    """Action: Remove a user from an organization."""

    action_type: Literal["delete_user"] = "delete_user"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    email: str = Field(..., description="User email")
    pk: int = Field(..., description="User primary key (resolved at planning time)")


class GlitchtipActionUpdateUserRole(BaseModel, frozen=True):
    """Action: Update a user's role in an organization."""

    action_type: Literal["update_user_role"] = "update_user_role"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="New role")
    pk: int = Field(..., description="User primary key (resolved at planning time)")


class GlitchtipActionCreateTeam(BaseModel, frozen=True):
    """Action: Create a team in an organization."""

    action_type: Literal["create_team"] = "create_team"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    team_slug: str = Field(..., description="Team slug")


class GlitchtipActionDeleteTeam(BaseModel, frozen=True):
    """Action: Delete a team from an organization."""

    action_type: Literal["delete_team"] = "delete_team"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    team_slug: str = Field(..., description="Team slug")


class GlitchtipActionAddUserToTeam(BaseModel, frozen=True):
    """Action: Add a user to a team."""

    action_type: Literal["add_user_to_team"] = "add_user_to_team"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    team_slug: str = Field(..., description="Team slug")
    email: str = Field(..., description="User email")
    pk: int | None = Field(
        default=None,
        description="User primary key (None when user is being invited in the same run)",
    )


class GlitchtipActionRemoveUserFromTeam(BaseModel, frozen=True):
    """Action: Remove a user from a team."""

    action_type: Literal["remove_user_from_team"] = "remove_user_from_team"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    team_slug: str = Field(..., description="Team slug")
    email: str = Field(..., description="User email")
    pk: int = Field(..., description="User primary key (resolved at planning time)")


class GlitchtipActionCreateProject(BaseModel, frozen=True):
    """Action: Create a project in an organization."""

    action_type: Literal["create_project"] = "create_project"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    project_name: str = Field(..., description="Project name")
    platform: str | None = Field(default=None, description="Project platform")
    event_throttle_rate: int = Field(
        default=0, description="Event throttle rate (0 = unlimited)"
    )
    teams: list[str] = Field(
        default_factory=list,
        description="Team slugs to associate with the project (first team used for creation)",
    )


class GlitchtipActionUpdateProject(BaseModel, frozen=True):
    """Action: Update a project's settings."""

    action_type: Literal["update_project"] = "update_project"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    project_slug: str = Field(..., description="Project slug")
    name: str = Field(..., description="Project name")
    platform: str | None = Field(default=None, description="Project platform")
    event_throttle_rate: int = Field(
        default=0, description="Event throttle rate (0 = unlimited)"
    )


class GlitchtipActionDeleteProject(BaseModel, frozen=True):
    """Action: Delete a project."""

    action_type: Literal["delete_project"] = "delete_project"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    project_slug: str = Field(..., description="Project slug")


class GlitchtipActionAddProjectToTeam(BaseModel, frozen=True):
    """Action: Add a project to a team."""

    action_type: Literal["add_project_to_team"] = "add_project_to_team"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    project_slug: str = Field(..., description="Project slug")
    team_slug: str = Field(..., description="Team slug")


class GlitchtipActionRemoveProjectFromTeam(BaseModel, frozen=True):
    """Action: Remove a project from a team."""

    action_type: Literal["remove_project_from_team"] = "remove_project_from_team"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    project_slug: str = Field(..., description="Project slug")
    team_slug: str = Field(..., description="Team slug")


# Union type for all 14 actions (discriminated by action_type)
GlitchtipAction = Annotated[
    GlitchtipActionCreateOrganization
    | GlitchtipActionDeleteOrganization
    | GlitchtipActionInviteUser
    | GlitchtipActionDeleteUser
    | GlitchtipActionUpdateUserRole
    | GlitchtipActionCreateTeam
    | GlitchtipActionDeleteTeam
    | GlitchtipActionAddUserToTeam
    | GlitchtipActionRemoveUserFromTeam
    | GlitchtipActionCreateProject
    | GlitchtipActionUpdateProject
    | GlitchtipActionDeleteProject
    | GlitchtipActionAddProjectToTeam
    | GlitchtipActionRemoveProjectFromTeam,
    Field(discriminator="action_type"),
]


class GlitchtipTaskResult(TaskResult, frozen=True):
    """Result model for completed Glitchtip reconciliation task."""

    actions: list[GlitchtipAction] = Field(
        default=[],
        description="All actions calculated (desired - current), including any that failed to apply.",
    )
    applied_actions: list[GlitchtipAction] = Field(
        default=[],
        description="Actions that were successfully applied (subset of actions, empty on dry_run).",
    )


class GlitchtipReconcileRequest(BaseModel, frozen=True):
    """Request model for Glitchtip reconciliation."""

    instances: list[GIInstance] = Field(
        ..., description="List of Glitchtip instances to reconcile"
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class GlitchtipTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile endpoint."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )
