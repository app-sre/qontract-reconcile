"""Pydantic schemas for the endpoints-discovery reconciliation API."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.endpoints_discovery.domain import (
    AppInterfaceRepo,
    DesiredApp,
)
from qontract_api.models import TaskResult, TaskStatus


class MergeRequestStatus(StrEnum):
    """Outcome of the merge request side effect.

    One MR covers every changed application, so the outcome belongs on the
    task result rather than on an individual action.
    """

    CREATED = "created"
    EXISTS = "exists"
    CLOSED_OUTDATED = "closed_outdated"
    NOT_NEEDED = "not_needed"
    FAILED = "failed"


class AddEndpointAction(BaseModel, frozen=True):
    """Action: add an endpoint rendered from the template."""

    action_type: Literal["add_endpoint"] = "add_endpoint"
    app_name: str = Field(..., description="Application name")
    app_path: str = Field(..., description="Application file path")
    cluster: str = Field(..., description="Cluster name")
    namespace: str = Field(..., description="Namespace name")
    endpoint_name: str = Field(..., description="New endpoint name")
    data: dict[str, Any] = Field(..., description="Rendered endpoint content")


class ChangeEndpointAction(BaseModel, frozen=True):
    """Action: replace an existing endpoint in place with rendered content."""

    action_type: Literal["change_endpoint"] = "change_endpoint"
    app_name: str = Field(..., description="Application name")
    app_path: str = Field(..., description="Application file path")
    cluster: str = Field(..., description="Cluster name")
    namespace: str = Field(..., description="Namespace name")
    endpoint_name: str = Field(..., description="Current endpoint name")
    data: dict[str, Any] = Field(..., description="Rendered endpoint content")


class DeleteEndpointAction(BaseModel, frozen=True):
    """Action: delete an existing endpoint."""

    action_type: Literal["delete_endpoint"] = "delete_endpoint"
    app_name: str = Field(..., description="Application name")
    app_path: str = Field(..., description="Application file path")
    endpoint_name: str = Field(..., description="Endpoint name to delete")
    cluster: str | None = Field(
        default=None,
        description="Cluster parsed from the endpoint name, when parseable",
    )
    namespace: str | None = Field(
        default=None,
        description="Namespace parsed from the endpoint name, when parseable",
    )


EndpointAction = Annotated[
    AddEndpointAction | ChangeEndpointAction | DeleteEndpointAction,
    Field(discriminator="action_type"),
]


class EndpointsDiscoveryReconcileRequest(BaseModel, frozen=True):
    """Request to reconcile application endpoints from live routes."""

    endpoint_template: str = Field(
        ...,
        description="Jinja2 template content from the App-Interface resource",
    )
    app_interface: AppInterfaceRepo = Field(
        ..., description="Repository the merge request targets"
    )
    apps: list[DesiredApp] = Field(
        ..., description="Applications with namespaces and current endpoints"
    )
    auto_merge: bool = Field(
        default=False,
        description="Whether to request automatic merging of the MR",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without opening an MR",
    )


class EndpointsDiscoveryTaskResult(TaskResult, frozen=True):
    """Result of an endpoints-discovery reconciliation task."""

    actions: list[EndpointAction] = Field(
        default=[], description="All planned endpoint changes"
    )
    applied_actions: list[EndpointAction] = Field(
        default=[],
        description="Actions written into a newly created MR (empty if dry_run)",
    )
    apps_with_changes: int = Field(
        default=0,
        description="Applications with at least one endpoint change",
    )
    mr_status: MergeRequestStatus | None = Field(
        default=None, description="Merge request outcome (None for dry-run)"
    )
    mr_url: str | None = Field(
        default=None, description="URL of the created or existing merge request"
    )


class EndpointsDiscoveryTaskResponse(BaseModel, frozen=True):
    """Response for POST /reconcile (202 Accepted)."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(..., description="Initial task status")
    status_url: str = Field(..., description="URL to poll for task result")
