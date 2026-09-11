"""Pydantic schemas for the quay-robot-accounts reconciliation API."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.quay_robot_accounts.domain import QuayOrgDesiredState
from qontract_api.models import TaskResult, TaskStatus


class QuayRobotActionCreate(BaseModel, frozen=True):
    """Action: Create a robot account."""

    action_type: Literal["create"] = "create"
    instance_name: str
    org_name: str
    robot_name: str
    description: str | None = None


class QuayRobotActionDelete(BaseModel, frozen=True):
    """Action: Delete a robot account (only when delete: true)."""

    action_type: Literal["delete"] = "delete"
    instance_name: str
    org_name: str
    robot_name: str


class QuayRobotActionAddTeam(BaseModel, frozen=True):
    """Action: Add a robot to a team."""

    action_type: Literal["add_team"] = "add_team"
    instance_name: str
    org_name: str
    robot_name: str
    team: str


class QuayRobotActionRemoveTeam(BaseModel, frozen=True):
    """Action: Remove a robot from a team."""

    action_type: Literal["remove_team"] = "remove_team"
    instance_name: str
    org_name: str
    robot_name: str
    team: str


class QuayRobotActionSetRepoPermission(BaseModel, frozen=True):
    """Action: Set or update a robot's repository permission."""

    action_type: Literal["set_repo_permission"] = "set_repo_permission"
    instance_name: str
    org_name: str
    robot_name: str
    repo: str
    permission: str


class QuayRobotActionRemoveRepoPermission(BaseModel, frozen=True):
    """Action: Remove a robot's repository permission."""

    action_type: Literal["remove_repo_permission"] = "remove_repo_permission"
    instance_name: str
    org_name: str
    robot_name: str
    repo: str


QuayRobotAction = Annotated[
    QuayRobotActionCreate
    | QuayRobotActionDelete
    | QuayRobotActionAddTeam
    | QuayRobotActionRemoveTeam
    | QuayRobotActionSetRepoPermission
    | QuayRobotActionRemoveRepoPermission,
    Field(discriminator="action_type"),
]


class QuayRobotAccountsTaskResult(TaskResult, frozen=True):
    """Result model for a completed quay-robot-accounts reconciliation task."""

    actions: list[QuayRobotAction] = Field(
        default=[],
        description="All actions calculated (desired - current), including any that failed to apply.",
    )
    applied_actions: list[QuayRobotAction] = Field(
        default=[],
        description="Actions that were successfully applied (non-dry-run only).",
    )


class QuayRobotAccountsReconcileRequest(BaseModel, frozen=True):
    """Request model for quay-robot-accounts reconciliation."""

    organizations: list[QuayOrgDesiredState] = Field(
        ...,
        description="Quay organizations with desired robot-account state",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class QuayRobotAccountsTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )


class QuayRobotAccountsErrorEvent(BaseModel, frozen=True):
    """Payload published when a reconciliation error is recorded."""

    error: str
