"""Pydantic schemas for RHIDP SSO client reconciliation API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.sso_client.domain import (
    KeycloakInstanceSecret,
    SsoClientCluster,
)
from qontract_api.models import Secret, TaskResult, TaskStatus


class SsoClientReconcileRequest(BaseModel, frozen=True):
    """Request model for RHIDP SSO client reconciliation.

    POST requests always queue a background task (async execution).
    """

    ocm_environment: str = Field(
        ..., description="OCM environment name (metric label only)"
    )
    clusters: list[SsoClientCluster] = Field(
        ..., description="All RHIDP-labeled clusters discovered for this environment"
    )
    keycloak_secrets: list[KeycloakInstanceSecret] = Field(
        ...,
        description="One entry per Keycloak instance (issuer URL + its Vault IAT secret reference)",
    )
    vault_target: Secret = Field(
        ...,
        description="Vault location to store/list/delete SSO client secrets under (field/version unused)",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class SsoClientActionCreate(BaseModel, frozen=True):
    """Action: register a new SSO client with Keycloak and store its secret."""

    action_type: Literal["create"] = "create"
    sso_client_id: str = Field(..., description="Vault secret id / Keycloak client id")
    cluster_name: str = Field(..., description="Cluster name")
    auth_name: str = Field(..., description="Auth name")


class SsoClientActionDelete(BaseModel, frozen=True):
    """Action: delete an SSO client from Keycloak and remove its stored secret."""

    action_type: Literal["delete"] = "delete"
    sso_client_id: str = Field(..., description="Vault secret id / Keycloak client id")


SsoClientAction = Annotated[
    SsoClientActionCreate | SsoClientActionDelete,
    Field(discriminator="action_type"),
]


class SsoClientTaskResult(TaskResult, frozen=True):
    """Result model for a completed reconciliation task."""

    actions: list[SsoClientAction] = Field(
        default=[],
        description="All actions calculated (desired - current), including any that failed to apply.",
    )
    applied_actions: list[SsoClientAction] = Field(
        default=[],
        description="Actions that were successfully applied (non-dry-run only).",
    )


class SsoClientTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile endpoint."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )
