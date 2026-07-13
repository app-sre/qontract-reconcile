from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from reconcile.aws_saml_roles.integration import (
    AwsRole,
    AwsSamlRolesIntegration,
)
from reconcile.gql_definitions.aws_saml_roles.aws_accounts import AWSAccountV1
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.terrascript_aws_client import TerrascriptClient

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture


def test_aws_saml_roles_get_early_exit_desired_state(
    intg: AwsSamlRolesIntegration, fixture_query_func: Callable
) -> None:
    state = intg.get_early_exit_desired_state(query_func=fixture_query_func)
    assert "roles" in state


def test_aws_saml_roles_get_aws_accounts(
    gql_class_factory: Callable,
    intg: AwsSamlRolesIntegration,
    fixture_query_func_aws_accounts: Callable,
) -> None:
    aws_accounts = [
        gql_class_factory(
            AWSAccountV1,
            {
                "sso": True,
                "name": "account-1",
                "uid": "1",
                "resourcesDefaultRegion": "us-east-1",
                "supportedDeploymentRegions": ["us-east-1", "us-east-2"],
                "providerVersion": "3.76.0",
                "accountOwners": [{"name": "owner", "email": "email@example.com"}],
                "automationToken": {"path": "/path/to/token", "field": "all"},
                "enableDeletion": True,
                "premiumSupport": True,
            },
        ),
        gql_class_factory(
            AWSAccountV1,
            {
                "sso": False,
                "name": "account-2",
                "uid": "1",
                "resourcesDefaultRegion": "us-east-1",
                "supportedDeploymentRegions": ["us-east-1", "us-east-2"],
                "providerVersion": "3.76.0",
                "accountOwners": [{"name": "owner", "email": "email@example.com"}],
                "automationToken": {"path": "/path/to/token", "field": "all"},
                "enableDeletion": True,
                "premiumSupport": True,
            },
        ),
    ]
    assert intg.get_aws_accounts(fixture_query_func_aws_accounts) == aws_accounts
    assert intg.get_aws_accounts(
        fixture_query_func_aws_accounts, account_name="account-1"
    ) == [aws_accounts[0]]


def test_aws_saml_roles_get_roles(
    gql_class_factory: Callable,
    intg: AwsSamlRolesIntegration,
    fixture_query_func: Callable,
) -> None:
    roles = [
        gql_class_factory(
            AwsRole,
            {
                "name": "uid-11111111-role-one-account-with-user-policies",
                "account": "account-1",
                "custom_policies": [
                    {
                        "name": "performance-insights-access",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "pi:*",
                                    "Resource": "arn:aws:pi:*:*:metrics/rds/*",
                                }
                            ],
                        },
                    },
                    {
                        "name": "rds-read-only",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "rds:DescribeDBInstances",
                                        "rds:DescribeDBClusters",
                                        "rds:DescribeGlobalClusters",
                                    ],
                                    "Resource": "*",
                                }
                            ],
                        },
                    },
                ],
                "managed_policies": [],
            },
        ),
        gql_class_factory(
            AwsRole,
            {
                "name": "uid-22222222-role-one-account-with-aws-groups",
                "account": "account-2",
                "custom_policies": [],
                "managed_policies": [
                    {"name": "IAMUserChangePassword"},
                    {"name": "CloudWatchReadOnlyAccess"},
                    {"name": "AmazonRDSReadOnlyAccess"},
                ],
            },
        ),
        gql_class_factory(
            AwsRole,
            {
                "name": "uid-33333333-role-one-account-with-user-policies-and-aws-groups",
                "account": "account-3",
                "custom_policies": [
                    {
                        "name": "performance-insights-access",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "pi:*",
                                    "Resource": "arn:aws:pi:*:*:metrics/rds/*",
                                }
                            ],
                        },
                    },
                    {
                        "name": "rds-read-only",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "rds:DescribeDBInstances",
                                        "rds:DescribeDBClusters",
                                        "rds:DescribeGlobalClusters",
                                    ],
                                    "Resource": "*",
                                }
                            ],
                        },
                    },
                ],
                "managed_policies": [
                    {"name": "IAMUserChangePassword"},
                    {"name": "CloudWatchReadOnlyAccess"},
                    {"name": "AmazonRDSReadOnlyAccess"},
                ],
            },
        ),
        gql_class_factory(
            AwsRole,
            {
                "name": "uid-22222222-role-two-accounta-with-user-policies-and-aws-groups",
                "account": "account-2",
                "custom_policies": [
                    {
                        "name": "performance-insights-access",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "pi:*",
                                    "Resource": "arn:aws:pi:*:*:metrics/rds/*",
                                }
                            ],
                        },
                    }
                ],
                "managed_policies": [
                    {"name": "IAMUserChangePassword"},
                    {"name": "CloudWatchReadOnlyAccess"},
                ],
            },
        ),
        gql_class_factory(
            AwsRole,
            {
                "name": "uid-33333333-role-two-accounta-with-user-policies-and-aws-groups",
                "account": "account-3",
                "custom_policies": [
                    {
                        "name": "rds-read-only",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "rds:DescribeDBInstances",
                                        "rds:DescribeDBClusters",
                                        "rds:DescribeGlobalClusters",
                                    ],
                                    "Resource": "*",
                                }
                            ],
                        },
                    }
                ],
                "managed_policies": [{"name": "AmazonRDSReadOnlyAccess"}],
            },
        ),
    ]
    assert intg.get_roles(fixture_query_func) == roles
    assert intg.get_roles(fixture_query_func, account_name="account-1") == [roles[0]]


def test_aws_saml_roles_populate_saml_iam_roles(
    gql_class_factory: Callable, mocker: MockerFixture, intg: AwsSamlRolesIntegration
) -> None:
    ts = mocker.MagicMock(spec=TerrascriptClient)
    roles = [
        gql_class_factory(
            AwsRole,
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [],
                "managed_policies": [
                    {"name": "IAMUserChangePassword"},
                    {"name": "CloudWatchReadOnlyAccess"},
                    {"name": "AmazonRDSReadOnlyAccess"},
                ],
            },
        ),
        gql_class_factory(
            AwsRole,
            {
                "name": "role-2",
                "account": "account-1",
                "custom_policies": [
                    {
                        "name": "rds-read-only",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "rds:DescribeDBInstances",
                                        "rds:DescribeDBClusters",
                                        "rds:DescribeGlobalClusters",
                                    ],
                                    "Resource": "*",
                                }
                            ],
                        },
                    }
                ],
                "managed_policies": [],
            },
        ),
        gql_class_factory(
            AwsRole,
            {
                "name": "role-3",
                "account": "account-1",
                "custom_policies": [
                    {
                        "name": "rds-read-only",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "rds:DescribeDBInstances",
                                        "rds:DescribeDBClusters",
                                        "rds:DescribeGlobalClusters",
                                    ],
                                    "Resource": "*",
                                }
                            ],
                        },
                    }
                ],
                "managed_policies": [
                    {"name": "IAMUserChangePassword"},
                    {"name": "CloudWatchReadOnlyAccess"},
                    {"name": "AmazonRDSReadOnlyAccess"},
                ],
            },
        ),
    ]
    unique_policies = intg._unique_policies(roles)
    intg.populate_saml_iam_roles(ts, roles, unique_policies)
    ts.populate_iam_policy.assert_called_once_with(
        account="account-1",
        name="rds-read-only",
        policy={
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "rds:DescribeDBInstances",
                        "rds:DescribeDBClusters",
                        "rds:DescribeGlobalClusters",
                    ],
                    "Resource": "*",
                }
            ],
        },
    )

    ts.populate_saml_iam_role.assert_has_calls([
        mocker.call(
            account="account-1",
            name="role-1",
            saml_provider_name="saml-idp",
            aws_managed_policies=[
                "IAMUserChangePassword",
                "CloudWatchReadOnlyAccess",
                "AmazonRDSReadOnlyAccess",
            ],
            customer_managed_policies=[],
            max_session_duration_hours=1,
        ),
        mocker.call(
            account="account-1",
            name="role-2",
            saml_provider_name="saml-idp",
            aws_managed_policies=[],
            customer_managed_policies=["rds-read-only"],
            max_session_duration_hours=1,
        ),
        mocker.call(
            account="account-1",
            name="role-3",
            saml_provider_name="saml-idp",
            aws_managed_policies=[
                "IAMUserChangePassword",
                "CloudWatchReadOnlyAccess",
                "AmazonRDSReadOnlyAccess",
            ],
            customer_managed_policies=["rds-read-only"],
            max_session_duration_hours=1,
        ),
    ])


def test_validate_saml_iam_policies_valid(
    gql_class_factory: Callable, intg: AwsSamlRolesIntegration
) -> None:
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.return_value = [{"findings": []}]
    mock_aws_api = MagicMock(spec=AWSApi)
    mock_aws_api._account_accessanalyzer_client.return_value = mock_aa
    roles = [
        gql_class_factory(
            AwsRole,
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [
                    {
                        "name": "rds-read-only",
                        "policy": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "rds:Describe*",
                                    "Resource": "*",
                                }
                            ],
                        },
                    }
                ],
                "managed_policies": [],
            },
        )
    ]
    intg._validate_saml_iam_policies(intg._unique_policies(roles), mock_aws_api)
    mock_aa.get_paginator.assert_called_once()


def test_validate_saml_iam_policies_invalid_raises(
    gql_class_factory: Callable, intg: AwsSamlRolesIntegration
) -> None:
    mock_aa = MagicMock()
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
    mock_aws_api = MagicMock(spec=AWSApi)
    mock_aws_api._account_accessanalyzer_client.return_value = mock_aa
    roles = [
        gql_class_factory(
            AwsRole,
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [
                    {
                        "name": "bad-policy",
                        "policy": {
                            "Statement": [
                                {"Effect": "Allow", "Action": "s3:*", "Resource": "*"}
                            ]
                        },
                    }
                ],
                "managed_policies": [],
            },
        )
    ]
    with pytest.raises(RuntimeError) as exc_info:
        intg._validate_saml_iam_policies(intg._unique_policies(roles), mock_aws_api)
    assert "iam_policy-bad-policy" in str(exc_info.value)


def test_validate_saml_iam_policies_multiple_errors_all_collected(
    gql_class_factory: Callable, intg: AwsSamlRolesIntegration
) -> None:
    mock_aa = MagicMock()
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
    mock_aws_api = MagicMock(spec=AWSApi)
    mock_aws_api._account_accessanalyzer_client.return_value = mock_aa
    roles = [
        gql_class_factory(
            AwsRole,
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [
                    {
                        "name": "bad-policy-1",
                        "policy": {
                            "Statement": [
                                {"Effect": "Allow", "Action": "s3:*", "Resource": "*"}
                            ]
                        },
                    },
                    {
                        "name": "bad-policy-2",
                        "policy": {
                            "Statement": [
                                {"Effect": "Allow", "Action": "ec2:*", "Resource": "*"}
                            ]
                        },
                    },
                ],
                "managed_policies": [],
            },
        )
    ]
    with pytest.raises(RuntimeError, match="AWS policy validation failed"):
        intg._validate_saml_iam_policies(intg._unique_policies(roles), mock_aws_api)
    assert mock_aa.get_paginator.call_count == 2


def test_validate_saml_iam_policies_no_custom_policies(
    gql_class_factory: Callable, intg: AwsSamlRolesIntegration
) -> None:
    mock_aws_api = MagicMock(spec=AWSApi)
    roles = [
        gql_class_factory(
            AwsRole,
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [],
                "managed_policies": [{"name": "ReadOnlyAccess"}],
            },
        )
    ]
    intg._validate_saml_iam_policies(intg._unique_policies(roles), mock_aws_api)
    mock_aws_api._account_accessanalyzer_client.assert_not_called()


@pytest.mark.parametrize(
    "role_dict",
    [
        pytest.param(
            {
                "name": "test" * 100,
                "account": "account-1",
                "custom_policies": [],
                "managed_policies": [],
            },
            id="role name too long",
        ),
        pytest.param(
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [{"name": "test" * 100, "policy": {}}],
                "managed_policies": [],
            },
            id="policy name too long",
        ),
        pytest.param(
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [
                    {
                        "name": "test",
                        "policy": {
                            "Statement": [
                                {"Effect": "Allow", "Action": "*", "Resource": "*"}
                            ]
                            * 200
                        },
                    }
                ],
                "managed_policies": [],
            },
            id="policy document too long",
        ),
        pytest.param(
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [],
                "managed_policies": [{"name": "test"}] * 21,
            },
            id="too many atttached policies 1",
        ),
        pytest.param(
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [{"name": "test" * 100, "policy": {}}] * 11,
                "managed_policies": [{"name": "test"}] * 10,
            },
            id="too many atttached policies 2",
        ),
        pytest.param(
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [
                    {"name": "test", "policy": {}},
                    {"name": "test", "policy": {}},
                ],
                "managed_policies": [],
            },
            id="duplicate policy names 1",
        ),
        pytest.param(
            {
                "name": "role-1",
                "account": "account-1",
                "custom_policies": [],
                "managed_policies": [
                    {"name": "test"},
                    {"name": "test"},
                ],
            },
            id="duplicate policy names 2",
        ),
    ],
)
def test_aws_saml_roles_aws_limits(role_dict: dict) -> None:
    with pytest.raises(ValueError):
        AwsRole(**role_dict)
