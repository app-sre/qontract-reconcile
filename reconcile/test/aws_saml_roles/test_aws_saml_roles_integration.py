from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.aws_saml_roles.integration import (
    AwsRole,
    AwsSamlRolesIntegration,
)
from reconcile.gql_definitions.aws_saml_roles.aws_accounts import AWSAccountV1
from reconcile.utils.terrascript_aws_client import TerrascriptClient


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
    intg.populate_saml_iam_roles(ts, roles)
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
