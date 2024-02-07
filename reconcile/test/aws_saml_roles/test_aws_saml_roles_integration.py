from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.aws_saml_roles.integration import (
    AwsSamlRolesIntegration,
)
from reconcile.gql_definitions.aws_saml_roles.aws_accounts import AWSAccountV1
from reconcile.gql_definitions.aws_saml_roles.aws_groups import AWSGroupV1
from reconcile.utils.terrascript_aws_client import TerrascriptClient


def test_aws_saml_roles_get_early_exit_desired_state(
    intg: AwsSamlRolesIntegration, fixture_query_func: Callable
) -> None:
    state = intg.get_early_exit_desired_state(query_func=fixture_query_func)
    assert "aws_groups" in state


def test_aws_saml_roles_get_aws_accounts(
    gql_class_factory: Callable,
    intg: AwsSamlRolesIntegration,
    fixture_query_func_aws_accounts: Callable,
) -> None:
    assert intg.get_aws_accounts(fixture_query_func_aws_accounts) == [
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
    assert intg.get_aws_accounts(
        fixture_query_func_aws_accounts, account_name="account-1"
    ) == [
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
        )
    ]


def test_aws_saml_roles_get_aws_groups(
    gql_class_factory: Callable,
    intg: AwsSamlRolesIntegration,
    fixture_query_func: Callable,
) -> None:
    assert intg.get_aws_groups(fixture_query_func) == [
        gql_class_factory(
            AWSGroupV1,
            {
                "name": "group-1",
                "account": {"name": "account-1", "uid": "1", "sso": True},
                "roles": [
                    {"users": [{"org_username": "user-1"}, {"org_username": "user-2"}]}
                ],
                "policies": ["AdministratorAccess"],
            },
        ),
        gql_class_factory(
            AWSGroupV1,
            {
                "name": "group-2",
                "account": {"name": "account-2", "uid": "2", "sso": True},
                "roles": [
                    {
                        "users": [
                            {"org_username": "other-user-1"},
                            {"org_username": "other-user-2"},
                        ]
                    }
                ],
                "policies": ["AdministratorAccess"],
            },
        ),
    ]
    assert intg.get_aws_groups(fixture_query_func, account_name="account-1") == [
        gql_class_factory(
            AWSGroupV1,
            {
                "name": "group-1",
                "account": {"name": "account-1", "uid": "1", "sso": True},
                "roles": [
                    {"users": [{"org_username": "user-1"}, {"org_username": "user-2"}]}
                ],
                "policies": ["AdministratorAccess"],
            },
        )
    ]


def test_aws_saml_roles_populate_saml_iam_roles(
    mocker: MockerFixture, intg: AwsSamlRolesIntegration, aws_groups: list[AWSGroupV1]
) -> None:
    ts = mocker.MagicMock(spec=TerrascriptClient)
    intg.populate_saml_iam_roles(ts, aws_groups)
    ts.populate_saml_iam_role.assert_has_calls([
        mocker.call(
            account="account-1",
            name="group-1",
            saml_provider_name="saml-idp",
            policies=["AdministratorAccess"],
            max_session_duration_hours=1,
        ),
        mocker.call(
            account="account-2",
            name="group-2",
            saml_provider_name="saml-idp",
            policies=["AdministratorAccess"],
            max_session_duration_hours=1,
        ),
    ])


def test_aws_saml_roles_populate_saml_iam_roles_duplicated_policy(
    mocker: MockerFixture, intg: AwsSamlRolesIntegration, aws_groups: list[AWSGroupV1]
) -> None:
    ts = mocker.MagicMock(spec=TerrascriptClient)
    aws_groups[0].policies = ["AdministratorAccess", "AdministratorAccess"]
    with pytest.raises(ValueError):
        intg.populate_saml_iam_roles(ts, aws_groups)
