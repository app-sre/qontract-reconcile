from collections.abc import Callable
from unittest.mock import ANY

import pytest

from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    AWSAccountsQueryData,
    AWSAccountV1,
)
from reconcile.typed_queries.terraform_tgw_attachments.aws_accounts import (
    get_aws_accounts,
)
from reconcile.utils.gql import GqlApi


@pytest.fixture
def aws_account(
    gql_class_factory: Callable[..., AWSAccountV1],
) -> AWSAccountV1:
    return gql_class_factory(
        AWSAccountV1,
        {
            "name": "some-account",
            "uid": "some-uid",
            "accountOwners": [],
            "automationToken": {},
            "premiumSupport": False,
        },
    )


@pytest.fixture
def aws_accounts(
    gql_class_factory: Callable[..., AWSAccountsQueryData],
    aws_account: AWSAccountV1,
) -> AWSAccountsQueryData:
    return gql_class_factory(
        AWSAccountsQueryData,
        {
            "accounts": [
                aws_account.dict(by_alias=True),
            ]
        },
    )


@pytest.fixture
def aws_accounts_with_no_data(
    gql_class_factory: Callable[..., AWSAccountsQueryData],
) -> AWSAccountsQueryData:
    return gql_class_factory(
        AWSAccountsQueryData,
        {
            "accounts": None,
        },
    )


def test_get_aws_accounts_with_default_variables(
    gql_api_builder: Callable[..., GqlApi],
    aws_accounts: AWSAccountsQueryData,
) -> None:
    gql_api = gql_api_builder(aws_accounts.dict(by_alias=True))

    result = get_aws_accounts(gql_api)

    assert result == aws_accounts.accounts
    expected_variables = {
        "name": None,
    }
    gql_api.query.assert_called_once_with(ANY, variables=expected_variables)


def test_get_aws_accounts_when_no_data(
    gql_api_builder: Callable[..., GqlApi],
    aws_accounts_with_no_data: AWSAccountsQueryData,
) -> None:
    gql_api = gql_api_builder(aws_accounts_with_no_data.dict(by_alias=True))

    result = get_aws_accounts(gql_api)

    assert result == []


def test_get_aws_accounts_with_name(
    gql_api_builder: Callable[..., GqlApi],
    aws_accounts: AWSAccountsQueryData,
) -> None:
    gql_api = gql_api_builder(aws_accounts.dict(by_alias=True))
    name = "some-name"

    result = get_aws_accounts(
        gql_api,
        name=name,
    )

    assert result == aws_accounts.accounts
    expected_variables = {
        "name": name,
    }
    gql_api.query.assert_called_once_with(ANY, variables=expected_variables)
