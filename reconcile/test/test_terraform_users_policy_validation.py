"""Tests for AWS policy validation in terraform_users using Access Analyzer."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from reconcile.terraform_users import _validate_aws_policies_in_roles
from reconcile.utils.aws_api import AWSApi


@pytest.fixture
def mock_accounts() -> list[dict[str, Any]]:
    return [
        {
            "name": "test-account-1",
            "resourcesDefaultRegion": "us-east-1",
        }
    ]


@pytest.fixture
def mock_aa() -> MagicMock:
    aa = MagicMock()
    aa.get_paginator.return_value.paginate.return_value = [{"findings": []}]
    return aa


@pytest.fixture
def mock_aws_api(mock_aa: MagicMock) -> MagicMock:
    api = MagicMock(spec=AWSApi)
    api._account_accessanalyzer_client.return_value = mock_aa
    return api


def test_validate_aws_policies_in_roles_valid_policies(
    mock_aws_api: MagicMock,
    mock_aa: MagicMock,
    mock_accounts: list[dict[str, Any]],
) -> None:
    roles = [
        {
            "name": "test-role-1",
            "user_policies": [
                {
                    "name": "s3-access",
                    "policy": '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::my-bucket/*"}]}',
                    "account": {"name": "test-account-1"},
                }
            ],
        },
        {
            "name": "test-role-2",
            "user_policies": [
                {
                    "name": "ec2-access",
                    "policy": '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["ec2:DescribeInstances", "ec2:DescribeImages"], "Resource": "*"}]}',
                    "account": {"name": "test-account-1"},
                }
            ],
        },
    ]

    _validate_aws_policies_in_roles(roles, mock_accounts, mock_aws_api)

    assert mock_aa.get_paginator.call_count == 2


def test_validate_aws_policies_in_roles_no_policies(
    mock_aws_api: MagicMock,
    mock_accounts: list[dict[str, Any]],
) -> None:
    roles: list[dict[str, Any]] = [
        {"name": "test-role-1", "user_policies": None},
        {"name": "test-role-2", "user_policies": []},
    ]

    _validate_aws_policies_in_roles(roles, mock_accounts, mock_aws_api)

    mock_aws_api._account_accessanalyzer_client.assert_not_called()


def test_validate_aws_policies_in_roles_invalid_policy(
    mock_aws_api: MagicMock,
    mock_aa: MagicMock,
    mock_accounts: list[dict[str, Any]],
) -> None:
    mock_aa.get_paginator.return_value.paginate.return_value = [
        {
            "findings": [
                {
                    "findingType": "ERROR",
                    "issueCode": "MISSING_VERSION",
                    "findingDetails": "The policy must include a Version element.",
                }
            ]
        }
    ]

    roles = [
        {
            "name": "test-role-1",
            "user_policies": [
                {
                    "name": "bad-policy",
                    "policy": '{"Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}',
                    "account": {"name": "test-account-1"},
                }
            ],
        }
    ]

    with pytest.raises(RuntimeError) as exc_info:
        _validate_aws_policies_in_roles(roles, mock_accounts, mock_aws_api)

    assert "user_policy-bad-policy" in str(exc_info.value)
    assert "MISSING_VERSION" in str(exc_info.value)


def test_validate_aws_policies_in_roles_multiple_invalid_policies(
    mock_aws_api: MagicMock,
    mock_aa: MagicMock,
    mock_accounts: list[dict[str, Any]],
) -> None:
    mock_aa.get_paginator.return_value.paginate.return_value = [
        {
            "findings": [
                {
                    "findingType": "ERROR",
                    "issueCode": "INVALID_ACTION",
                    "findingDetails": "The action is not valid.",
                }
            ]
        }
    ]

    roles = [
        {
            "name": "test-role-1",
            "user_policies": [
                {
                    "name": "policy1",
                    "policy": '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "invalid:action", "Resource": "*"}]}',
                    "account": {"name": "test-account-1"},
                },
                {
                    "name": "policy2",
                    "policy": '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}]}',
                    "account": {"name": "test-account-1"},
                },
            ],
        }
    ]

    with pytest.raises(RuntimeError):
        _validate_aws_policies_in_roles(roles, mock_accounts, mock_aws_api)

    assert mock_aa.get_paginator.call_count == 2


def test_validate_aws_policies_handles_dict_policy(
    mock_aws_api: MagicMock,
    mock_aa: MagicMock,
    mock_accounts: list[dict[str, Any]],
) -> None:
    roles = [
        {
            "name": "test-role-1",
            "user_policies": [
                {
                    "name": "dict-policy",
                    "policy": {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Action": "s3:GetObject",
                                "Resource": "*",
                            }
                        ],
                    },
                    "account": {"name": "test-account-1"},
                }
            ],
        }
    ]

    _validate_aws_policies_in_roles(roles, mock_accounts, mock_aws_api)

    mock_aa.get_paginator.assert_called_once()


def test_validate_aws_policies_in_roles_skips_sso_accounts(
    mock_aws_api: MagicMock,
    mock_accounts: list[dict[str, Any]],
) -> None:
    roles = [
        {
            "name": "test-role-1",
            "user_policies": [
                {
                    "name": "sso-policy",
                    "policy": '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}',
                    "account": {"name": "test-account-1", "sso": True},
                }
            ],
        }
    ]

    _validate_aws_policies_in_roles(roles, mock_accounts, mock_aws_api)

    mock_aws_api._account_accessanalyzer_client.assert_not_called()


def test_validate_aws_policies_in_roles_skips_account_not_in_scope(
    mock_aws_api: MagicMock,
    mock_accounts: list[dict[str, Any]],
) -> None:
    roles = [
        {
            "name": "test-role-1",
            "user_policies": [
                {
                    "name": "out-of-scope-policy",
                    "policy": '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}]}',
                    "account": {"name": "another-account"},
                }
            ],
        }
    ]

    _validate_aws_policies_in_roles(roles, mock_accounts, mock_aws_api)

    mock_aws_api._account_accessanalyzer_client.assert_not_called()
