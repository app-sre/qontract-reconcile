"""Pydantic schemas for OCM OIDC identity provider reconciliation API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.ocm_oidc_idp.domain import OcmOidcIdpCluster
from qontract_api.models import Secret, TaskResult, TaskStatus
from qontract_api.ocm.domain import OcmConnectionParams


class OcmOidcIdpReconcileRequest(BaseModel, frozen=True):
    """Request model for OCM OIDC identity provider reconciliation.

    POST requests always queue a background task (async execution).
    """

    ocm_environment: str = Field(
        ..., description="OCM environment name (metric label only)"
    )
    ocm_connection: OcmConnectionParams = Field(
        ..., description="OCM connection details, needed for identity provider CRUD"
    )
    clusters: list[OcmOidcIdpCluster] = Field(
        ..., description="All RHIDP-labeled clusters discovered for this environment"
    )
    vault_target: Secret = Field(
        ...,
        description=(
            "Vault location sso_client stores per-cluster SSO client secrets under "
            "(field/version unused)"
        ),
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class OcmOidcIdpActionCreate(BaseModel, frozen=True):
    """Action: create a new OIDC identity provider on a cluster."""

    action_type: Literal["create"] = "create"
    cluster_name: str = Field(..., description="Cluster name")
    auth_name: str = Field(..., description="Identity provider name")


class OcmOidcIdpActionUpdate(BaseModel, frozen=True):
    """Action: update an existing OIDC identity provider on a cluster."""

    action_type: Literal["update"] = "update"
    cluster_name: str = Field(..., description="Cluster name")
    auth_name: str = Field(..., description="Identity provider name")


class OcmOidcIdpActionDelete(BaseModel, frozen=True):
    """Action: delete an identity provider from a cluster."""

    action_type: Literal["delete"] = "delete"
    cluster_name: str = Field(..., description="Cluster name")
    idp_name: str = Field(..., description="Identity provider name")


OcmOidcIdpAction = Annotated[
    OcmOidcIdpActionCreate | OcmOidcIdpActionUpdate | OcmOidcIdpActionDelete,
    Field(discriminator="action_type"),
]


class OcmOidcIdpTaskResult(TaskResult, frozen=True):
    """Result model for a completed reconciliation task."""

    actions: list[OcmOidcIdpAction] = Field(
        default=[],
        description="All actions calculated (desired - current), including any that failed to apply.",
    )
    applied_actions: list[OcmOidcIdpAction] = Field(
        default=[],
        description="Actions that were successfully applied (non-dry-run only).",
    )


class OcmOidcIdpTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile endpoint."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )
