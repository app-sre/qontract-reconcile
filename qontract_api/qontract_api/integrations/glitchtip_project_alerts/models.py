"""Pydantic models for Glitchtip project alerts reconciliation API."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.models import Secret, TaskResult, TaskStatus


class GlitchtipInstance(BaseModel, frozen=True):
    """Glitchtip instance configuration."""

    name: str = Field(..., description="Instance name (unique identifier)")
    console_url: str = Field(..., description="Glitchtip instance base URL")
    token: Secret = Field(..., description="Secret reference for the API token")
    read_timeout: int = Field(default=30, description="HTTP read timeout in seconds")
    max_retries: int = Field(default=3, description="Max HTTP retries")


class GlitchtipProjectAlertRecipient(BaseModel, frozen=True):
    """Desired state for a single project alert recipient."""

    recipient_type: str = Field(..., description="Recipient type: 'email' or 'webhook'")
    url: str = Field(default="", description="Webhook URL (empty for email recipients)")


class GlitchtipProjectAlert(BaseModel, frozen=True):
    """Desired state for a single project alert."""

    name: str = Field(
        ..., description="Alert name (unique identifier within a project)"
    )
    timespan_minutes: int = Field(
        ..., description="Time window in minutes for alert evaluation"
    )
    quantity: int = Field(..., description="Number of events to trigger the alert")
    recipients: list[GlitchtipProjectAlertRecipient] = Field(
        default=[], description="List of alert recipients"
    )


class GlitchtipProject(BaseModel, frozen=True):
    """Desired state for a single Glitchtip project's alerts."""

    name: str = Field(..., description="Project name")
    slug: str = Field(..., description="Project slug (URL-friendly identifier)")
    alerts: list[GlitchtipProjectAlert] = Field(
        default=[], description="Desired alerts for this project"
    )


class GlitchtipOrganization(BaseModel, frozen=True):
    """Desired state for a single Glitchtip organization's projects."""

    name: str = Field(..., description="Organization name")
    projects: list[GlitchtipProject] = Field(
        default=[], description="Projects within this organization"
    )


class GlitchtipProjectAlertsReconcileRequest(BaseModel, frozen=True):
    """Request model for Glitchtip project alerts reconciliation.

    POST requests always queue a background task (async execution).
    """

    instances: list[GlitchtipInstance] = Field(
        ..., description="List of Glitchtip instances to reconcile"
    )
    desired_state: dict[str, list[GlitchtipOrganization]] = Field(
        ...,
        description="Desired state keyed by instance name, containing organizations with project alerts",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


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

    actions: list[
        GlitchtipAlertActionCreate
        | GlitchtipAlertActionUpdate
        | GlitchtipAlertActionDelete
    ] = Field(
        default=[],
        description="List of actions calculated/performed",
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
