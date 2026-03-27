"""Pydantic schemas for Glitchtip project alerts reconciliation API."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.glitchtip_project_alerts.domain import GlitchtipInstance
from qontract_api.models import TaskResult, TaskStatus


# Type-safe action models
class GlitchtipAlertActionCreate(BaseModel, frozen=True):
    """Action: Create a new project alert."""

    action_type: Literal["create"] = "create"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    project: str = Field(..., description="Project slug")
    alert_name: str = Field(..., description="Alert name")


class GlitchtipAlertActionUpdate(BaseModel, frozen=True):
    """Action: Update an existing project alert."""

    action_type: Literal["update"] = "update"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    project: str = Field(..., description="Project slug")
    alert_name: str = Field(..., description="Alert name")


class GlitchtipAlertActionDelete(BaseModel, frozen=True):
    """Action: Delete a project alert."""

    action_type: Literal["delete"] = "delete"
    instance: str = Field(..., description="Glitchtip instance name")
    organization: str = Field(..., description="Organization name")
    project: str = Field(..., description="Project slug")
    alert_name: str = Field(..., description="Alert name")


# Union type for all actions
GlitchtipAlertAction = Annotated[
    GlitchtipAlertActionCreate
    | GlitchtipAlertActionUpdate
    | GlitchtipAlertActionDelete,
    Field(discriminator="action_type"),
]


class GlitchtipProjectAlertsTaskResult(TaskResult, frozen=True):
    """Result model for completed reconciliation task.

    Returned by GET /reconcile/{task_id}.
    """

    actions: list[GlitchtipAlertAction] = Field(
        default=[],
        description="All actions calculated (desired - current), including any that failed to apply.",
    )
    applied_actions: list[GlitchtipAlertAction] = Field(
        default=[],
        description="Actions that were successfully applied (non-dry-run only).",
    )


class GlitchtipProjectAlertsReconcileRequest(BaseModel, frozen=True):
    """Request model for Glitchtip project alerts reconciliation.

    POST requests always queue a background task (async execution).
    """

    instances: list[GlitchtipInstance] = Field(
        ..., description="List of Glitchtip instances to reconcile"
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class GlitchtipProjectAlertsTaskResponse(BaseModel, frozen=True):
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
