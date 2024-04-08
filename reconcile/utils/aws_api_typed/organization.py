import functools
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Optional

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

    def locate(
        self, path: list[str], ignore_case: bool = True
    ) -> Optional["AwsOrganizationOU"]:
        name, *sub = path
        match = self.name.lower() == name.lower() if ignore_case else self.name == name
        if not match:
            return None
        if not sub:
            return self
        return next(
            (
                result
                for child in self.children
                if (result := child.locate(sub, ignore_case=ignore_case))
            ),
            None,
        )

    def find(self, path: str, ignore_case: bool = True) -> "AwsOrganizationOU":
        node = self.locate(path.strip("/").split("/"), ignore_case=ignore_case)
        if not node:
            raise KeyError(f"OU not found: {path}")
        return node

    def __hash__(self) -> int:
        return hash(self.id)


class AWSAccountStatus(BaseModel):
    id: str = Field(..., alias="Id")
    name: str = Field(..., alias="AccountName")
    uid: str | None = Field(alias="AccountId")
    state: str = Field(..., alias="State")
    failure_reason: CreateAccountFailureReasonType | None = Field(alias="FailureReason")


class AWSAccount(BaseModel):
    name: str = Field(..., alias="Name")
    uid: str = Field(..., alias="Id")
    email: str = Field(..., alias="Email")
    state: str = Field(..., alias="Status")


class AWSAccountCreationException(Exception):
    """Exception raised when account creation failed."""


class AWSAccountNotFoundException(Exception):
    """Exception raised when the account cannot be found in the specified OU."""


class AWSApiOrganizations:
    def __init__(self, client: OrganizationsClient) -> None:
        self.client = client
        self.get_organizational_units_tree = functools.lru_cache(maxsize=None)(
            self._get_organizational_units_tree
        )

    def _get_organizational_units_tree(
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
        self, email: str, name: str, access_to_billing: bool = True
    ) -> AWSAccountStatus:
        """Create a new account in the organization."""
        resp = self.client.create_account(
            Email=email,
            AccountName=name,
            IamUserAccessToBilling="ALLOW" if access_to_billing else "DENY",
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

    def get_ou(self, uid: str) -> str:
        """Return the organizational unit ID of an account."""
        resp = self.client.list_parents(ChildId=uid)
        for p in resp.get("Parents", []):
            if p["Type"] in {"ORGANIZATIONAL_UNIT", "ROOT"}:
                return p["Id"]
        raise AWSAccountNotFoundException(f"Account {uid} not found!")

    def move_account(self, uid: str, destination_parent_id: str) -> None:
        """Move an account to a different organizational unit."""
        source_parent_id = self.get_ou(uid=uid)
        if source_parent_id == destination_parent_id:
            return
        self.client.move_account(
            AccountId=uid,
            SourceParentId=source_parent_id,
            DestinationParentId=destination_parent_id,
        )

    def describe_account(self, uid: str) -> AWSAccount:
        """Return the status of an account."""
        resp = self.client.describe_account(AccountId=uid)
        return AWSAccount(**resp["Account"])

    def tag_resource(self, resource_id: str, tags: Mapping[str, str]) -> None:
        """Tag a resource."""
        self.client.tag_resource(
            ResourceId=resource_id,
            Tags=[{"Key": k, "Value": v} for k, v in tags.items()],
        )

    def untag_resource(self, resource_id: str, tag_keys: Iterable[str]) -> None:
        """Untag a resource."""
        self.client.untag_resource(ResourceId=resource_id, TagKeys=list(tag_keys))
