from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from qontract_utils.aws_api_typed.organization import (
    AWSAccountCreationError,
    AWSAccountNotFoundError,
    AWSApiOrganizations,
)

if TYPE_CHECKING:
    from mypy_boto3_organizations import OrganizationsClient
    from pytest_mock import MockerFixture


@pytest.fixture
def organization_client(mocker: MockerFixture) -> OrganizationsClient:
    return mocker.Mock()


@pytest.fixture
def aws_api_organizations(
    organization_client: OrganizationsClient,
) -> AWSApiOrganizations:
    return AWSApiOrganizations(client=organization_client)


def test_aws_api_typed_organizations_get_organizational_units_tree(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    organization_client.list_roots.return_value = {
        "Roots": [
            {
                "Id": "root_id",
                "Arn": "root_arn",
                "Name": "root_name",
                "PolicyTypes": [],
            }
        ]
    }
    paginator_mock = MagicMock()
    paginator_mock.paginate.side_effect = [
        [
            {
                "OrganizationalUnits": [
                    {
                        "Id": "ou_id",
                        "Arn": "ou_arn",
                        "Name": "ou_name",
                        "PolicyTypes": [],
                    }
                ]
            }
        ],
        [],
    ]
    organization_client.get_paginator.return_value = paginator_mock

    tree = aws_api_organizations.get_organizational_units_tree()
    assert tree.id == "root_id"
    assert tree.arn == "root_arn"
    assert tree.name == "root_name"
    assert tree.children[0].id == "ou_id"
    assert tree.children[0].arn == "ou_arn"
    assert tree.children[0].name == "ou_name"


def test_aws_api_typed_organizations_move_account(
    aws_api_organizations: AWSApiOrganizations,
    organization_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(AWSApiOrganizations, "get_ou")
    aws_api_organizations.get_ou.return_value = "source_parent_id"  # type: ignore
    aws_api_organizations.move_account("account_id", "destination_parent_id")
    organization_client.move_account.assert_called_once_with(
        AccountId="account_id",
        SourceParentId="source_parent_id",
        DestinationParentId="destination_parent_id",
    )


def test_aws_api_typed_organizations_get_ou(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    organization_client.list_parents.return_value = {
        "Parents": [
            {
                "Id": "ou_id",
                "Type": "ORGANIZATIONAL_UNIT",
            },
        ]
    }
    ou_id = aws_api_organizations.get_ou("account_id")
    assert ou_id == "ou_id"


def test_aws_api_typed_organizations_get_ou_not_found(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    organization_client.list_parents.return_value = {"Parents": []}
    with pytest.raises(AWSAccountNotFoundError):
        aws_api_organizations.get_ou("account_id")


def test_aws_api_typed_organizations_move_account_already_moved(
    aws_api_organizations: AWSApiOrganizations,
    organization_client: MagicMock,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(AWSApiOrganizations, "get_ou")
    aws_api_organizations.get_ou.return_value = "destination_parent_id"  # type: ignore
    aws_api_organizations.move_account("account_id", "destination_parent_id")
    organization_client.move_account.assert_not_called()


def test_aws_api_typed_organizations_describe_create_account_status(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    organization_client.describe_create_account_status.return_value = {
        "CreateAccountStatus": {
            "Id": "id",
            "AccountName": "account_name",
            "State": "state",
            "RequestedTimestamp": "1708592227",
            "CompletedTimestamp": "1708592235",
            "AccountId": "account_id",
        }
    }
    status = aws_api_organizations.describe_create_account_status(
        "create_account_request_id"
    )
    assert status.id == "id"
    assert status.name == "account_name"
    assert status.uid == "account_id"
    assert status.state == "state"
    assert not status.failure_reason


def test_aws_api_typed_organizations_create_account(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    organization_client.create_account.return_value = {
        "CreateAccountStatus": {
            "Id": "id",
            "AccountName": "account_name",
            "State": "state",
            "RequestedTimestamp": "1708592227",
            "CompletedTimestamp": "1708592235",
            "AccountId": "account_id",
        }
    }
    status = aws_api_organizations.create_account("email", "account_name", True)
    assert status.id == "id"
    assert status.name == "account_name"
    assert status.uid == "account_id"
    assert status.state == "state"
    assert not status.failure_reason
    organization_client.create_account.assert_called_once_with(
        Email="email", AccountName="account_name", IamUserAccessToBilling="ALLOW"
    )


def test_aws_api_typed_organizations_create_account_error(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    organization_client.create_account.return_value = {
        "CreateAccountStatus": {
            "Id": "id",
            "AccountName": "account_name",
            "State": "FAILED",
            "RequestedTimestamp": "1708592227",
            "CompletedTimestamp": "1708592235",
            "AccountId": "account_id",
            "FailureReason": "ACCOUNT_LIMIT_EXCEEDED",
        }
    }
    with pytest.raises(AWSAccountCreationError):
        aws_api_organizations.create_account("email", "account_name", True)
    organization_client.create_account.assert_called_once_with(
        Email="email",
        AccountName="account_name",
        IamUserAccessToBilling="ALLOW",
    )


def test_aws_api_typed_organizations_tag_resource(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    aws_api_organizations.tag_resource("resource_id", {"key": "value"})
    organization_client.tag_resource.assert_called_once_with(
        ResourceId="resource_id", Tags=[{"Key": "key", "Value": "value"}]
    )


def test_aws_api_typed_organizations_untag_resource(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    aws_api_organizations.untag_resource("resource_id", ["key"])
    organization_client.untag_resource.assert_called_once_with(
        ResourceId="resource_id", TagKeys=["key"]
    )
