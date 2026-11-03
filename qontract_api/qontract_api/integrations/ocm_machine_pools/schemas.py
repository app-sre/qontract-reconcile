"""Pydantic API request/response schemas for OCM machine pool reconciliation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.ocm_machine_pools.domain import (
    DesiredClusterMachinePools,
)
from qontract_api.models import TaskResult, TaskStatus
from qontract_api.ocm.domain import OcmConnectionParams


class OcmMachinePoolsReconcileRequest(BaseModel, frozen=True):
    """Request model for OCM machine pool reconciliation.

    POST requests always queue a background task (async execution).
    """

    ocm_environment: str = Field(
        ..., description="OCM environment name (metric label only)"
    )
    ocm_connection: OcmConnectionParams = Field(
        ..., description="OCM connection details for machine/node pool CRUD"
    )
    clusters: list[DesiredClusterMachinePools] = Field(
        ..., description="Clusters with their desired machine/node pools"
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "If True, only calculate actions without executing. "
            "Default: True (safety first!)"
        ),
    )


class OcmMachinePoolsActionCreateMachinePool(BaseModel, frozen=True):
    """Action: create a machine pool (OSD / ROSA classic cluster)."""

    action_type: Literal["create_machine_pool"] = "create_machine_pool"
    cluster: str = Field(..., description="Cluster name")
    pool_id: str = Field(..., description="Machine pool id")


class OcmMachinePoolsActionUpdateMachinePool(BaseModel, frozen=True):
    """Action: update a machine pool (OSD / ROSA classic cluster)."""

    action_type: Literal["update_machine_pool"] = "update_machine_pool"
    cluster: str = Field(..., description="Cluster name")
    pool_id: str = Field(..., description="Machine pool id")


class OcmMachinePoolsActionDeleteMachinePool(BaseModel, frozen=True):
    """Action: delete a machine pool (OSD / ROSA classic cluster)."""

    action_type: Literal["delete_machine_pool"] = "delete_machine_pool"
    cluster: str = Field(..., description="Cluster name")
    pool_id: str = Field(..., description="Machine pool id")


class OcmMachinePoolsActionCreateNodePool(BaseModel, frozen=True):
    """Action: create a node pool (ROSA HCP cluster)."""

    action_type: Literal["create_node_pool"] = "create_node_pool"
    cluster: str = Field(..., description="Cluster name")
    pool_id: str = Field(..., description="Node pool id")


class OcmMachinePoolsActionUpdateNodePool(BaseModel, frozen=True):
    """Action: update a node pool (ROSA HCP cluster)."""

    action_type: Literal["update_node_pool"] = "update_node_pool"
    cluster: str = Field(..., description="Cluster name")
    pool_id: str = Field(..., description="Node pool id")


class OcmMachinePoolsActionDeleteNodePool(BaseModel, frozen=True):
    """Action: delete a node pool (ROSA HCP cluster)."""

    action_type: Literal["delete_node_pool"] = "delete_node_pool"
    cluster: str = Field(..., description="Cluster name")
    pool_id: str = Field(..., description="Node pool id")


OcmMachinePoolsAction = Annotated[
    OcmMachinePoolsActionCreateMachinePool
    | OcmMachinePoolsActionUpdateMachinePool
    | OcmMachinePoolsActionDeleteMachinePool
    | OcmMachinePoolsActionCreateNodePool
    | OcmMachinePoolsActionUpdateNodePool
    | OcmMachinePoolsActionDeleteNodePool,
    Field(discriminator="action_type"),
]


class OcmMachinePoolsTaskResult(TaskResult, frozen=True):
    """Result model for a completed OCM machine pool reconciliation task."""

    actions: list[OcmMachinePoolsAction] = Field(
        default=[],
        description=(
            "All actions calculated (desired - current), "
            "including any that failed to apply."
        ),
    )
    applied_actions: list[OcmMachinePoolsAction] = Field(
        default=[],
        description="Actions that were successfully applied (non-dry-run only).",
    )


class OcmMachinePoolsTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile endpoint."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )
