from unittest.mock import MagicMock

import botocore
import pytest
from mypy_boto3_account import AccountClient
from pytest_mock import MockerFixture

from qontract_utils.aws_api_typed.account import AWSApiAccount, OptStatus, Region


@pytest.fixture
def account_client(mocker: MockerFixture) -> AccountClient:
    return mocker.MagicMock(spec=AccountClient)


@pytest.fixture
def aws_api_account(account_client: AccountClient) -> AWSApiAccount:
    return AWSApiAccount(client=account_client)


def test_aws_api_typed_account_set_security_contact(
    aws_api_account: AWSApiAccount, account_client: MagicMock
) -> None:
    account_client.put_alternate_contact.return_value = None
    aws_api_account.set_security_contact(
        name="name",
        title="title",
        email="email",
        phone_number="phone_number",
    )


def test_aws_api_typed_account_set_security_contact_permission_denied_by_already_set(
    aws_api_account: AWSApiAccount, account_client: MagicMock
) -> None:
    account_client.exceptions.AccessDeniedException = botocore.exceptions.ClientError
    account_client.put_alternate_contact.side_effect = botocore.exceptions.ClientError(
        error_response={
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "User: arn:aws:iam::xxxx:user/terraform is not authorized to perform: account:PutAlternateContact on resource: arn:aws:account::787755075174:account with an explicit deny",
            }
        },
        operation_name="PutAlternateContact",
    )
    account_client.get_alternate_contact.return_value = {
        "AlternateContact": {
            "EmailAddress": "email",
            "Name": "name",
            "Title": "title",
            "PhoneNumber": "phone_number",
        }
    }
    aws_api_account.set_security_contact(
        name="name",
        title="title",
        email="email",
        phone_number="phone_number",
    )


def test_aws_api_typed_account_set_security_contact_permission_denied_and_not_set(
    aws_api_account: AWSApiAccount, account_client: MagicMock
) -> None:
    account_client.exceptions.AccessDeniedException = botocore.exceptions.ClientError
    account_client.put_alternate_contact.side_effect = botocore.exceptions.ClientError(
        error_response={
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "User: arn:aws:iam::xxxx:user/terraform is not authorized to perform: account:PutAlternateContact on resource: arn:aws:account::787755075174:account with an explicit deny",
            }
        },
        operation_name="PutAlternateContact",
    )
    account_client.get_alternate_contact.return_value = {"AlternateContact": None}
    with pytest.raises(botocore.exceptions.ClientError):
        aws_api_account.set_security_contact(
            name="name",
            title="title",
            email="email",
            phone_number="phone_number",
        )


def test_aws_api_typed_account_set_security_contact_permission_denied_and_different(
    aws_api_account: AWSApiAccount, account_client: MagicMock
) -> None:
    account_client.exceptions.AccessDeniedException = botocore.exceptions.ClientError
    account_client.put_alternate_contact.side_effect = botocore.exceptions.ClientError(
        error_response={
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "User: arn:aws:iam::xxxx:user/terraform is not authorized to perform: account:PutAlternateContact on resource: arn:aws:account::787755075174:account with an explicit deny",
            }
        },
        operation_name="PutAlternateContact",
    )
    account_client.get_alternate_contact.return_value = {
        "AlternateContact": {
            "EmailAddress": "different_email",
            "Name": "name",
            "Title": "title",
            "PhoneNumber": "phone_number",
        }
    }
    with pytest.raises(botocore.exceptions.ClientError):
        aws_api_account.set_security_contact(
            name="name",
            title="title",
            email="email",
            phone_number="phone_number",
        )


def test_aws_api_typed_account_get_security_contact(
    aws_api_account: AWSApiAccount, account_client: MagicMock
) -> None:
    account_client.get_alternate_contact.return_value = {
        "AlternateContact": {
            "EmailAddress": "email",
            "Name": "name",
            "Title": "title",
            "PhoneNumber": "phone_number",
        }
    }
    contact = aws_api_account.get_security_contact()
    assert contact is not None
    assert contact["EmailAddress"] == "email"
    assert contact["Name"] == "name"
    assert contact["Title"] == "title"
    assert contact["PhoneNumber"] == "phone_number"
    account_client.get_alternate_contact.assert_called_once_with(
        AlternateContactType="SECURITY"
    )


def test_aws_api_typed_account_list_regions(
    aws_api_account: AWSApiAccount, account_client: MagicMock
) -> None:
    paginator_mock = MagicMock()
    paginator_mock.paginate.side_effect = [
        [
            {
                "Regions": [
                    {
                        "RegionOptStatus": "ENABLED",
                        "RegionName": "region-enabled",
                    },
                    {
                        "RegionOptStatus": "ENABLING",
                        "RegionName": "region-enabling",
                    },
                    {
                        "RegionOptStatus": "DISABLED",
                        "RegionName": "region-disabled",
                    },
                    {
                        "RegionOptStatus": "DISABLING",
                        "RegionName": "region-disabling",
                    },
                    {
                        "RegionOptStatus": "ENABLED_BY_DEFAULT",
                        "RegionName": "region-enabled-by-default",
                    },
                ]
            }
        ],
        [],
    ]
    account_client.get_paginator.return_value = paginator_mock

    assert aws_api_account.list_regions() == [
        Region(name="region-enabled", status=OptStatus.ENABLED),
        Region(name="region-enabling", status=OptStatus.ENABLED),
        Region(name="region-disabled", status=OptStatus.DISABLED),
        Region(name="region-disabling", status=OptStatus.DISABLED),
        Region(name="region-enabled-by-default", status=OptStatus.ENABLED_BY_DEFAULT),
    ]


def test_aws_api_typed_account_enable_region(
    aws_api_account: AWSApiAccount, account_client: MagicMock
) -> None:
    aws_api_account.enable_region("region")
    account_client.enable_region.assert_called_once_with(RegionName="region")


def test_aws_api_typed_account_disable_region(
    aws_api_account: AWSApiAccount, account_client: MagicMock
) -> None:
    aws_api_account.disable_region("region")
    account_client.disable_region.assert_called_once_with(RegionName="region")
