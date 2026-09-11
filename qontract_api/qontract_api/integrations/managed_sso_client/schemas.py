"""Pydantic schemas for the managed-sso-client reconciliation API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.managed_sso_client.domain import (
    ManagedSsoClientDesiredState,
)
from qontract_api.models import TaskResult, TaskStatus


class ManagedSsoClientActionCreate(BaseModel, frozen=True):
    """Action: register a new managed SSO client with Keycloak."""

    action_type: Literal["create"] = "create"
    client_id: str = Field(
        ..., description="Exact Keycloak clientId of the client being created."
    )
    tenant_secret_path: str = Field(
        ..., description="Vault path of the tenant-facing credential secret."
    )


class ManagedSsoClientActionUpdate(BaseModel, frozen=True):
    """Action: update an existing managed SSO client's OIDC configuration on Keycloak.

    Keycloak-only - a change to the tenant secret's output path is an
    independent concern, represented by its own ManagedSsoClientActionMoveTenantSecret.
    """

    action_type: Literal["update"] = "update"
    client_id: str = Field(
        ..., description="Exact Keycloak clientId of the client being updated."
    )


class ManagedSsoClientActionMoveTenantSecret(BaseModel, frozen=True):
    """Action: migrate the tenant secret to a newly-resolved output path.

    Pure Vault bookkeeping - reuses the client_secret Keycloak already
    issued, no Keycloak call involved. Independent of, and may co-occur
    with, ManagedSsoClientActionUpdate.
    """

    action_type: Literal["move_tenant_secret"] = "move_tenant_secret"
    client_id: str = Field(
        ...,
        description="Exact Keycloak clientId of the client whose tenant secret is moving.",
    )
    tenant_secret_path: str = Field(
        ..., description="New Vault path of the tenant-facing credential secret."
    )


class ManagedSsoClientActionDelete(BaseModel, frozen=True):
    """Action: delete a managed SSO client no longer present in desired state."""

    action_type: Literal["delete"] = "delete"
    client_id: str = Field(
        ..., description="Exact Keycloak clientId of the client being deleted."
    )


ManagedSsoClientAction = Annotated[
    ManagedSsoClientActionCreate
    | ManagedSsoClientActionUpdate
    | ManagedSsoClientActionMoveTenantSecret
    | ManagedSsoClientActionDelete,
    Field(discriminator="action_type"),
]


class ManagedSsoClientTaskResult(TaskResult, frozen=True):
    """Result model for a completed managed-sso-client reconciliation task."""

    actions: list[ManagedSsoClientAction] = Field(
        default=[],
        description="All actions calculated (desired vs. current), including any that failed to apply.",
    )
    applied_actions: list[ManagedSsoClientAction] = Field(
        default=[],
        description="Actions that were successfully applied (non-dry-run only).",
    )


class ManagedSsoClientReconcileRequest(BaseModel, frozen=True):
    """Request model for managed-sso-client reconciliation.

    POST requests always queue a background task (async execution).
    """

    desired_clients: list[ManagedSsoClientDesiredState] = Field(
        ..., description="All tenant-declared managed SSO clients across app-interface"
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing. Default: True (safety first!)",
    )


class ManagedSsoClientTaskResponse(BaseModel, frozen=True):
    """Response model for POST /reconcile."""

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )


class ManagedSsoClientErrorEvent(BaseModel, frozen=True):
    """Payload published when a reconciliation error is recorded."""

    error: str = Field(
        ..., description="The error message recorded during reconciliation."
    )
