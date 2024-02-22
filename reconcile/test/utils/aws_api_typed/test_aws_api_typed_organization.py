from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.aws_api_typed.organization import (
    AWSAccountCreationException,
    AWSApiOrganizations,
)

if TYPE_CHECKING:
    from mypy_boto3_organizations import OrganizationsClient
else:
    OrganizationsClient = object


@pytest.fixture
def organization_client(mocker: MockerFixture) -> OrganizationsClient:
    return mocker.Mock()


@pytest.fixture
def aws_api_organizations(
    organization_client: OrganizationsClient,
) -> AWSApiOrganizations:
    return AWSApiOrganizations(client=organization_client)


def test_aws_api_typed_organizations_move_account(
    aws_api_organizations: AWSApiOrganizations, organization_client: MagicMock
) -> None:
    aws_api_organizations.move_account(
        "account_id", "source_parent_id", "destination_parent_id"
    )
    organization_client.move_account.assert_called_once_with(
        AccountId="account_id",
        SourceParentId="source_parent_id",
        DestinationParentId="destination_parent_id",
    )


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
    assert status.account_name == "account_name"
    assert status.account_id == "account_id"
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
    status = aws_api_organizations.create_account(
        "email", "account_name", {"key": "value"}, True
    )
    assert status.id == "id"
    assert status.account_name == "account_name"
    assert status.account_id == "account_id"
    assert status.state == "state"
    assert not status.failure_reason
    organization_client.create_account.assert_called_once_with(
        Email="email",
        AccountName="account_name",
        IamUserAccessToBilling="ALLOW",
        Tags=[{"Key": "key", "Value": "value"}],
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
    with pytest.raises(AWSAccountCreationException):
        aws_api_organizations.create_account(
            "email", "account_name", {"key": "value"}, True
        )
    organization_client.create_account.assert_called_once_with(
        Email="email",
        AccountName="account_name",
        IamUserAccessToBilling="ALLOW",
        Tags=[{"Key": "key", "Value": "value"}],
    )
