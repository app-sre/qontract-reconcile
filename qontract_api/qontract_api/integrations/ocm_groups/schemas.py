"""Pydantic API request/response schemas for OCM groups reconciliation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.ocm_groups.domain import OcmGroupsCluster, OcmGroupUser
from qontract_api.models import TaskResult, TaskStatus
from qontract_api.ocm.domain import OcmConnectionParams


class OcmGroupsReconcileRequest(BaseModel, frozen=True):
    """Request model for OCM groups reconciliation.

    POST requests always queue a background task (async execution).
    """

    ocm_environment: str = Field(
        ..., description="OCM environment name (metric label only)"
    )
    ocm_connection: OcmConnectionParams = Field(
        ..., description="OCM connection details for cluster group CRUD"
    )
    clusters: list[OcmGroupsCluster] = Field(
        ..., description="Clusters with their managed groups"
    )
    desired_state: list[OcmGroupUser] = Field(
        ..., description="Desired group memberships (from GraphQL roles)"
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "If True, only calculate actions without executing. "
            "Default: True (safety first!)"
        ),
    )


class OcmGroupsActionAddUser(BaseModel, frozen=True):
    """Action: add a user to a cluster group."""

    action_type: Literal["add_user_to_group"] = "add_user_to_group"
    cluster: str = Field(..., description="Cluster name")
    group: str = Field(..., description="Group name")
    user: str = Field(..., description="Username to add")


class OcmGroupsActionDeleteUser(BaseModel, frozen=True):
    """Action: remove a user from a cluster group."""

    action_type: Literal["delete_user_from_group"] = "delete_user_from_group"
    cluster: str = Field(..., description="Cluster name")
    group: str = Field(..., description="Group name")
    user: str = Field(..., description="Username to remove")


OcmGroupsAction = Annotated[
    OcmGroupsActionAddUser | OcmGroupsActionDeleteUser,
    Field(discriminator="action_type"),
]


class OcmGroupsTaskResult(TaskResult, frozen=True):
    """Result model for a completed OCM groups reconciliation task."""

    actions: list[OcmGroupsAction] = Field(
        default=[],
        description=(
            "All actions calculated (desired - current), "
            "including any that failed to apply."
        ),
    )
    applied_actions: list[OcmGroupsAction] = Field(
        default=[],
        description="Actions that were successfully applied (non-dry-run only).",
    )


class OcmGroupsTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile endpoint."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )
