from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.aws_api_typed.account import AWSApiAccount

if TYPE_CHECKING:
    from mypy_boto3_account import AccountClient
else:
    AccountClient = object


@pytest.fixture
def account_client(mocker: MockerFixture) -> AccountClient:
    return mocker.Mock()


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
