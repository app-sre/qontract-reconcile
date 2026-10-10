"""Pydantic API request/response schemas for ldap-groups reconciliation."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from qontract_api.integrations.ldap_groups.domain import Group
from qontract_api.internal_groups.domain import InternalGroupsConnectionSecret
from qontract_api.models import TaskResult, TaskStatus


class LdapGroupsReconcileRequest(BaseModel, frozen=True):
    """Request model for ldap-groups reconciliation."""

    connection: InternalGroupsConnectionSecret = Field(
        ..., description="Internal Groups API connection and Vault credentials"
    )
    desired_groups: list[Group] = Field(
        ..., description="Desired groups compiled from App-Interface roles"
    )
    managed_group_names: list[str] = Field(
        default=[],
        description="Previously managed group names from client S3 state",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing",
    )


class LdapGroupsActionCreate(BaseModel, frozen=True):
    action_type: Literal["create_ldap_group"] = "create_ldap_group"
    name: str
    members: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    notes: str | None = None


class LdapGroupsActionUpdate(BaseModel, frozen=True):
    action_type: Literal["update_ldap_group"] = "update_ldap_group"
    name: str
    members: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    notes: str | None = None


class LdapGroupsActionDelete(BaseModel, frozen=True):
    action_type: Literal["delete_ldap_group"] = "delete_ldap_group"
    name: str


LdapGroupsAction = Annotated[
    LdapGroupsActionCreate | LdapGroupsActionUpdate | LdapGroupsActionDelete,
    Field(discriminator="action_type"),
]


class LdapGroupsErrorEvent(BaseModel, frozen=True):
    """Payload published when a reconciliation error is recorded."""

    error: str = Field(
        ..., description="The error message recorded during reconciliation."
    )


class LdapGroupsTaskResult(TaskResult, frozen=True):
    """Result for a completed ldap-groups reconciliation task."""

    actions: list[LdapGroupsAction] = Field(default_factory=list)
    applied_actions: list[LdapGroupsAction] = Field(default_factory=list)
    updated_managed_groups: list[str] = Field(
        default_factory=list,
        description="Managed group names after reconciliation (persist to S3 client-side)",
    )


class LdapGroupsTaskResponse(BaseModel, frozen=True):
    id: str
    status: TaskStatus = TaskStatus.PENDING
    status_url: str
