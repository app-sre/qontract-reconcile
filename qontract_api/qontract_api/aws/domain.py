"""Pydantic domain models for AWS account management."""

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class AWSAccountOrganization(BaseModel, frozen=True):
    """Organization membership details for an AWS account."""

    ou: str = Field(..., description="Organizational Unit path")
    tags: dict[str, str] = Field(
        default_factory=dict, description="Tags to apply to the account"
    )


class AWSQuota(BaseModel, frozen=True):
    """Service quota configuration for an AWS account."""

    service_code: str = Field(..., description="AWS service code (e.g., 'vpc')")
    quota_code: str = Field(
        ..., description="Quota code within the service (e.g., 'L-F678F1CE')"
    )
    value: float = Field(..., description="Desired quota value")


class AWSSecurityContact(BaseModel, frozen=True):
    """Security contact information for an AWS account."""

    name: str = Field(..., description="Contact name")
    title: str | None = Field(None, description="Contact title")
    email: str = Field(..., description="Contact email address")
    phone_number: str = Field(..., description="Contact phone number")


class AWSAccountRequest(BaseModel, frozen=True):
    """Request to create a new AWS account under a payer account."""

    name: str = Field(..., description="Account name")
    email: str = Field(..., description="Account owner email")
    uid: str | None = Field(
        None, description="Existing account ID for takeover scenarios"
    )
    path: str = Field(..., description="App-interface path to account request file")


class AWSOrganizationAccount(BaseModel, frozen=True):
    """An existing AWS account managed within an organization."""

    name: str = Field(..., description="Account name")
    uid: str = Field(..., description="AWS account ID")
    organization: AWSAccountOrganization = Field(
        ..., description="Organization membership details"
    )
    enterprise_support: bool = Field(
        ..., description="Whether enterprise support is required"
    )
    alias: str | None = Field(None, description="Account alias")
    quotas: list[AWSQuota] = Field(
        default_factory=list, description="Service quota configurations"
    )
    security_contact: AWSSecurityContact = Field(
        ..., description="Security contact information"
    )
    supported_deployment_regions: list[str] = Field(
        default_factory=list, description="Regions to enable for this account"
    )


class AWSPayerAccount(BaseModel, frozen=True):
    """A payer (management) account in an AWS organization."""

    name: str = Field(..., description="Account name")
    uid: str = Field(..., description="AWS account ID")
    automation_token: Secret = Field(
        ..., description="Secret reference for automation credentials"
    )
    automation_role: str = Field(..., description="IAM role ARN for account management")
    resources_default_region: str = Field(
        ..., description="Default AWS region for API calls"
    )
    organization_account_tags: dict[str, str] = Field(
        default_factory=dict, description="Default tags for organization accounts"
    )
