from collections.abc import Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mypy_boto3_organizations import OrganizationsClient
    from mypy_boto3_organizations.literals import CreateAccountFailureReasonType
else:
    OrganizationsClient = object
    CreateAccountFailureReasonType = object


class AwsOrganizationOU(BaseModel):
    id: str = Field(..., alias="Id")
    arn: str = Field(..., alias="Arn")
    name: str = Field(..., alias="Name")
    children: list["AwsOrganizationOU"] = []

    def find(self, path: str) -> "AwsOrganizationOU":
        """Return an organizational unit by its path."""
        name, *rest = path.strip("/").split("/")
        subs = "/".join(rest)
        if self.name == name:
            if not rest:
                return self
            for child in self.children:
                try:
                    return child.find(subs)
                except KeyError:
                    pass
        raise KeyError(f"OU not found: {path}")


class AWSAccountStatus(BaseModel):
    id: str = Field(..., alias="Id")
    account_name: str = Field(..., alias="AccountName")
    account_id: str = Field(..., alias="AccountId")
    state: str = Field(..., alias="State")
    failure_reason: CreateAccountFailureReasonType | None = Field(alias="FailureReason")


class AWSAccountCreationException(Exception):
    pass


class AWSApiOrganizations:
    def __init__(self, client: OrganizationsClient) -> None:
        self.client = client

    def get_organizational_units_tree(
        self, root: AwsOrganizationOU | None = None
    ) -> AwsOrganizationOU:
        """List all organizational units for a given root recursively."""
        if not root:
            root = AwsOrganizationOU(**self.client.list_roots()["Roots"][0])

        paginator = self.client.get_paginator("list_organizational_units_for_parent")
        for page in paginator.paginate(ParentId=root.id):
            for ou_raw in page["OrganizationalUnits"]:
                ou = AwsOrganizationOU(**ou_raw)
                root.children.append(ou)
                self.get_organizational_units_tree(root=ou)
        return root

    def create_account(
        self,
        email: str,
        account_name: str,
        tags: Mapping[str, str],
        access_to_billing: bool = True,
    ) -> AWSAccountStatus:
        """Create a new account in the organization."""
        resp = self.client.create_account(
            Email=email,
            AccountName=account_name,
            IamUserAccessToBilling="ALLOW" if access_to_billing else "DENY",
            Tags=[{"Key": k, "Value": v} for k, v in tags.items()],
        )
        status = AWSAccountStatus(**resp["CreateAccountStatus"])
        if status.state == "FAILED":
            raise AWSAccountCreationException(
                f"Account creation failed: {status.failure_reason}"
            )
        return status

    def describe_create_account_status(
        self, create_account_request_id: str
    ) -> AWSAccountStatus:
        """Return the status of a create account request."""
        resp = self.client.describe_create_account_status(
            CreateAccountRequestId=create_account_request_id
        )
        return AWSAccountStatus(**resp["CreateAccountStatus"])

    def move_account(
        self, account_id: str, source_parent_id: str, destination_parent_id: str
    ) -> None:
        """Move an account to a different organizational unit."""
        self.client.move_account(
            AccountId=account_id,
            SourceParentId=source_parent_id,
            DestinationParentId=destination_parent_id,
        )
