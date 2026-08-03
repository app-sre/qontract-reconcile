"""Pydantic schemas for openshift-namespaces reconciliation API."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.openshift_namespaces.domain import ClusterNamespaces
from qontract_api.models import TaskResult, TaskStatus


class CreateNamespaceAction(BaseModel, frozen=True):
    """Action: Create a namespace on a cluster."""

    action_type: Literal["create_namespace"] = "create_namespace"
    cluster: str = Field(..., description="Cluster name")
    namespace: str = Field(..., description="Namespace name")


class DeleteNamespaceAction(BaseModel, frozen=True):
    """Action: Delete a namespace from a cluster."""

    action_type: Literal["delete_namespace"] = "delete_namespace"
    cluster: str = Field(..., description="Cluster name")
    namespace: str = Field(..., description="Namespace name")


NamespaceAction = Annotated[
    CreateNamespaceAction | DeleteNamespaceAction,
    Field(discriminator="action_type"),
]


class OpenShiftNamespacesReconcileRequest(BaseModel, frozen=True):
    """Request to reconcile namespaces across clusters."""

    clusters: list[ClusterNamespaces] = Field(
        ..., description="Clusters with desired namespaces"
    )
    dry_run: bool = Field(
        default=True, description="If True, only calculate actions without executing"
    )


class OpenShiftNamespacesTaskResult(TaskResult, frozen=True):
    """Result of a namespace reconciliation task."""

    actions: list[NamespaceAction] = Field(
        default=[], description="All planned actions"
    )
    applied_actions: list[NamespaceAction] = Field(
        default=[], description="Actions that were applied (empty if dry_run)"
    )


class OpenShiftNamespacesTaskResponse(BaseModel, frozen=True):
    """Response for POST /reconcile (202 Accepted)."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(..., description="Initial task status")
    status_url: str = Field(..., description="URL to poll for task result")
