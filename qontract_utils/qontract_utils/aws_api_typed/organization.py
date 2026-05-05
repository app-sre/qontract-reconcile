from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS, AWSApiCallContext
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from mypy_boto3_organizations import OrganizationsClient
    from mypy_boto3_organizations.literals import CreateAccountFailureReasonType
else:
    # pydantic needs these types to be defined during runtime
    CreateAccountFailureReasonType = str


class AwsOrganizationOU(BaseModel):
    id: str = Field(..., alias="Id")
    arn: str = Field(..., alias="Arn")
    name: str = Field(..., alias="Name")
    children: list[AwsOrganizationOU] = []

    def locate(
        self, path: list[str], *, ignore_case: bool = True
    ) -> AwsOrganizationOU | None:
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

    def find(self, path: str, *, ignore_case: bool = True) -> AwsOrganizationOU:
        node = self.locate(path.strip("/").split("/"), ignore_case=ignore_case)
        if not node:
            raise KeyError(f"OU not found: {path}")
        return node

    def __hash__(self) -> int:
        return hash(self.id)


class AWSAccountStatus(BaseModel):
    id: str = Field(..., alias="Id")
    name: str = Field(..., alias="AccountName")
    uid: str | None = Field(None, alias="AccountId")
    state: str = Field(..., alias="State")
    failure_reason: CreateAccountFailureReasonType | None = Field(
        None, alias="FailureReason"
    )


class AWSAccount(BaseModel):
    name: str = Field(..., alias="Name")
    uid: str = Field(..., alias="Id")
    email: str = Field(..., alias="Email")
    state: str = Field(..., alias="Status")


class AWSAccountCreationError(Exception):
    """Exception raised when account creation failed."""


class AWSAccountNotFoundError(Exception):
    """Exception raised when the account cannot be found in the specified OU."""


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiOrganizations:
    _hooks: Hooks

    def __init__(self, client: OrganizationsClient, hooks: Hooks | None = None) -> None:  # noqa: ARG002
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

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="create_account", service="organizations")
    )
    def create_account(
        self, email: str, name: str, *, access_to_billing: bool = True
    ) -> AWSAccountStatus:
        """Create a new account in the organization."""
        resp = self.client.create_account(
            Email=email,
            AccountName=name,
            IamUserAccessToBilling="ALLOW" if access_to_billing else "DENY",
        )
        status = AWSAccountStatus(**resp["CreateAccountStatus"])
        if status.state == "FAILED":
            raise AWSAccountCreationError(
                f"Account creation failed: {status.failure_reason}"
            )
        return status

    @invoke_with_hooks(
        lambda: AWSApiCallContext(
            method="describe_create_account_status", service="organizations"
        )
    )
    def describe_create_account_status(
        self, create_account_request_id: str
    ) -> AWSAccountStatus:
        """Return the status of a create account request."""
        resp = self.client.describe_create_account_status(
            CreateAccountRequestId=create_account_request_id
        )
        return AWSAccountStatus(**resp["CreateAccountStatus"])

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="get_ou", service="organizations")
    )
    def get_ou(self, uid: str) -> str:
        """Return the organizational unit ID of an account."""
        resp = self.client.list_parents(ChildId=uid)
        for p in resp.get("Parents", []):
            if p["Type"] in {"ORGANIZATIONAL_UNIT", "ROOT"}:
                return p["Id"]
        raise AWSAccountNotFoundError(f"Account {uid} not found!")

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="move_account", service="organizations")
    )
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

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="describe_account", service="organizations")
    )
    def describe_account(self, uid: str) -> AWSAccount:
        """Return the status of an account."""
        resp = self.client.describe_account(AccountId=uid)
        return AWSAccount(**resp["Account"])

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="tag_resource", service="organizations")
    )
    def tag_resource(self, resource_id: str, tags: Mapping[str, str]) -> None:
        """Tag a resource."""
        self.client.tag_resource(
            ResourceId=resource_id,
            Tags=[{"Key": k, "Value": v} for k, v in tags.items()],
        )

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="untag_resource", service="organizations")
    )
    def untag_resource(self, resource_id: str, tag_keys: Iterable[str]) -> None:
        """Untag a resource."""
        self.client.untag_resource(ResourceId=resource_id, TagKeys=list(tag_keys))
