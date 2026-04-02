"""Pydantic schemas for AWS account manager API.

Per-account design: each API call handles exactly one account.
"""

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from qontract_api.aws.domain import (
    AWSAccountOrganization,
    AWSAccountRequest,
    AWSPayerAccount,
    AWSQuota,
    AWSSecurityContact,
)
from qontract_api.models import Secret, TaskResult, TaskStatus

# --- Create account request ---


class AWSAccountManagerCreateAccountRequest(BaseModel, frozen=True):
    """Request to create a plain AWS account.

    Handles only AWS-level operations: create org account, describe,
    tag, set alias. One payer account + one account request per call.
    """

    payer_account: AWSPayerAccount = Field(
        ...,
        description="Payer account with credentials",
    )
    account_request: AWSAccountRequest = Field(..., description="Account to create")
    organization_account_role: str = Field(
        default="OrganizationAccountAccessRole",
        description="Role to assume in the new account",
    )
    default_tags: dict[str, str] = Field(
        default_factory=dict,
        description="Default tags for the new account",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing.",
    )

    @property
    def workflow_id(self) -> str:
        """Deterministic hash of the request for deduplication."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


# --- Create IAM user request ---


class AWSAccountManagerCreateIAMUserRequest(BaseModel, frozen=True):
    """Request to create an IAM user in an AWS account.

    Assumes into the account via the payer's manager role and creates
    an IAM user with the specified policy. Credentials are saved to Vault.
    """

    payer_account: AWSPayerAccount = Field(
        ...,
        description="Payer account with credentials",
    )
    account_name: str = Field(..., description="Name of the target account")
    account_uid: str = Field(..., description="AWS account ID of the target account")
    organization_account_role: str = Field(
        default="OrganizationAccountAccessRole",
        description="Role to assume in the target account",
    )
    user_name: str = Field(..., description="Name of the IAM user to create")
    policy_arn: str = Field(..., description="Policy ARN to attach to the IAM user")
    secret_vault_path: str = Field(
        ...,
        description="Vault path for storing IAM credentials",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing.",
    )


# --- Reconcile request ---


class AWSAccountManagerReconcileRequest(BaseModel, frozen=True):
    """Request to reconcile a single AWS account.

    If ``organization`` is present, the account is treated as an organization
    account (payer credentials + role assumption). Otherwise it is a standalone
    account with direct credentials.
    """

    account_name: str = Field(..., description="Account name")
    uid: str = Field(..., description="AWS account ID")
    automation_token: Secret = Field(
        ...,
        description="Credentials (payer's for org accounts, own for non-org)",
    )
    resources_default_region: str = Field(..., description="Default AWS region")
    payer_uid: str | None = Field(
        None,
        description="Payer account UID (required for org accounts — role assumed on payer, not org account)",
    )

    # Account settings to reconcile
    alias: str | None = Field(None, description="Desired account alias")
    quotas: list[AWSQuota] = Field(
        default_factory=list,
        description="Desired service quotas",
    )
    security_contact: AWSSecurityContact = Field(
        ...,
        description="Desired security contact",
    )
    supported_deployment_regions: list[str] = Field(
        default_factory=list,
        description="Desired enabled regions",
    )

    # Organization context (presence = org account)
    organization: AWSAccountOrganization | None = Field(
        None,
        description="Organization details (OU + tags). If set, account is org-managed.",
    )
    automation_role: str | None = Field(
        None,
        description="Payer's manager role ARN (required for org accounts)",
    )
    organization_account_role: str = Field(
        default="OrganizationAccountAccessRole",
        description="Role to assume in org account",
    )
    enterprise_support: bool = Field(
        default=False,
        description="Whether enterprise support is required",
    )
    default_tags: dict[str, str] = Field(
        default_factory=dict,
        description="Default tags for the account",
    )

    dry_run: bool = Field(
        default=True,
        description="If True, only calculate actions without executing.",
    )

    @property
    def is_org_account(self) -> bool:
        """Whether this is an organization-managed account."""
        return self.organization is not None


# --- Per-endpoint result models ---


class AccountCreateCompleteAction(BaseModel, frozen=True):
    """Account creation completed — contains the created account's name and UID."""

    action_type: Literal["create_complete"] = "create_complete"
    account_name: str = Field(..., description="Name of the created account")
    payer_account_name: str = Field(
        ...,
        description="Name of the payer account that managed creation",
    )
    account_uid: str = Field(..., description="AWS account ID of the created account")


class CreateAccountResult(TaskResult, frozen=True):
    """Result for GET /create-account/{task_id}.

    On completion, contains the created account's name and UID.
    """

    actions: list[AccountCreateCompleteAction] = Field(
        default_factory=list,
        description="Completed account creation (empty while in progress)",
    )


class AccountCreateIAMUserAction(BaseModel, frozen=True):
    """IAM user creation action — contains account and user details."""

    action_type: Literal["create_iam_user"] = "create_iam_user"
    account_name: str = Field(..., description="Name of the account")
    user_name: str = Field(..., description="IAM user name created")
    detail: str = Field(default="", description="Additional detail")


class CreateIAMUserResult(TaskResult, frozen=True):
    """Result for GET /create-iam-user/{task_id}.

    Contains IAM user creation details.
    """

    actions: list[AccountCreateIAMUserAction] = Field(
        default_factory=list,
        description="IAM user creation actions performed",
    )


class ReconcileActionTag(BaseModel, frozen=True):
    """Action: account tags updated."""

    action_type: Literal["tag"] = "tag"
    account_name: str = Field(..., description="Account name")
    tags: dict[str, str] = Field(..., description="Applied tags")


class ReconcileActionMoveOU(BaseModel, frozen=True):
    """Action: account moved to a different OU."""

    action_type: Literal["move_ou"] = "move_ou"
    account_name: str = Field(..., description="Account name")
    ou: str = Field(..., description="Target OU path")


class ReconcileActionSetAlias(BaseModel, frozen=True):
    """Action: account alias set."""

    action_type: Literal["set_alias"] = "set_alias"
    account_name: str = Field(..., description="Account name")
    alias: str = Field(..., description="Applied alias")


class ReconcileActionRequestQuota(BaseModel, frozen=True):
    """Action: service quota increase requested."""

    action_type: Literal["request_quota"] = "request_quota"
    account_name: str = Field(..., description="Account name")
    service_code: str = Field(..., description="AWS service code")
    quota_code: str = Field(..., description="AWS quota code")
    value: float = Field(..., description="Requested quota value")


class ReconcileActionEnableSupport(BaseModel, frozen=True):
    """Action: enterprise support enabled."""

    action_type: Literal["enable_support"] = "enable_support"
    account_name: str = Field(..., description="Account name")


class ReconcileActionSetSecurityContact(BaseModel, frozen=True):
    """Action: security contact set."""

    action_type: Literal["set_security_contact"] = "set_security_contact"
    account_name: str = Field(..., description="Account name")


class ReconcileActionSetRegions(BaseModel, frozen=True):
    """Action: supported regions updated."""

    action_type: Literal["set_regions"] = "set_regions"
    account_name: str = Field(..., description="Account name")
    enabled: list[str] = Field(default_factory=list, description="Regions enabled")
    disabled: list[str] = Field(default_factory=list, description="Regions disabled")


ReconcileAction = (
    ReconcileActionTag
    | ReconcileActionMoveOU
    | ReconcileActionSetAlias
    | ReconcileActionRequestQuota
    | ReconcileActionEnableSupport
    | ReconcileActionSetSecurityContact
    | ReconcileActionSetRegions
)


class ReconcileResult(TaskResult, frozen=True):
    """Result for GET /reconcile/{task_id}.

    Success/failure status for account reconciliation.
    """

    actions: list[ReconcileAction] = Field(
        default_factory=list,
        description="Reconciliation actions performed",
    )


class AWSAccountManagerTaskResponse(BaseModel, frozen=True):
    """Response model for POST endpoints.

    Returned immediately when task is queued. Contains task_id and status_url
    for retrieving the result via GET request.
    """

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ...,
        description="URL to retrieve task result (GET request)",
    )
