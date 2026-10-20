"""Typed IAM prerequisite coverage for infrastructure-access grants."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from qontract_utils.aws_api_typed.api import AWSStaticCredentials
from qontract_utils.aws_api_typed.iam import AWSUser

from reconcile import ocm_aws_infrastructure_access as infrastructure
from reconcile.gql_definitions.ocm_aws_infrastructure_access.clusters import ClusterV1
from reconcile.test.utils.membershipsources.fixtures import build_ldap_membership_source

if TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_mock import MockerFixture


@pytest.mark.parametrize(
    ("partition", "region"),
    [("aws", "us-east-1"), ("aws-us-gov", "us-gov-west-1")],
)
def test_infrastructure_prerequisite_uses_typed_iam_client(
    partition: str,
    region: str,
    gql_class_factory: Callable,
    mocker: MockerFixture,
) -> None:
    cluster = gql_class_factory(
        ClusterV1,
        {
            "name": "cluster",
            "awsInfrastructureAccess": [
                {
                    "accessLevel": "read-only",
                    "awsGroup": {
                        "account": {
                            "name": "account",
                            "uid": "123456789012",
                            "resourcesDefaultRegion": region,
                            "partition": partition,
                            "automationToken": {"path": "aws/token"},
                        },
                        "roles": [
                            {
                                "name": "team",
                                "users": [
                                    {"org_username": "alice", "aws_username": "custom"},
                                    {"org_username": "bob", "aws_username": None},
                                ],
                            }
                        ],
                    },
                }
            ],
        },
    )
    assert cluster.aws_infrastructure_access is not None
    assert cluster.aws_infrastructure_access[0].aws_group.roles is not None
    cluster.aws_infrastructure_access[0].aws_group.roles[0].member_sources = [
        build_ldap_membership_source("ldap", "team")
    ]
    mocker.patch.object(infrastructure, "get_app_interface_vault_settings")
    mocker.patch.object(infrastructure.queries, "get_aws_accounts", return_value=[])
    mocker.patch.object(infrastructure, "get_namespaces", return_value=[])
    reader = mocker.patch.object(infrastructure, "create_secret_reader").return_value
    reader.read_all_secret.return_value = {
        "aws_access_key_id": "test-access",
        "aws_secret_access_key": "test-secret",
    }
    constructor = mocker.patch.object(infrastructure, "AWSApi")
    client = constructor.return_value.__enter__.return_value
    client._get_account_users.return_value = ["custom", "bob"]
    client.iam.list_users.return_value = [
        AWSUser(UserName=name, UserId=f"id-{name}", Arn=f"arn/{name}", Path="/")
        for name in ("custom", "bob")
    ]
    grants = infrastructure.fetch_desired_state([cluster])
    assert constructor.call_args.args[0] == AWSStaticCredentials(
        access_key_id="test-access", secret_access_key="test-secret", region=region
    )
    assert constructor.call_args.kwargs == {}
    client.iam.list_users.assert_called_once_with()
    client._get_account_users.assert_not_called()
    reader.read_all_secret.assert_called_once_with(
        cluster.aws_infrastructure_access[0].aws_group.account.automation_token
    )
    constructor.return_value.__exit__.assert_called_once()
    assert {grant.user_arn for grant in grants} == {
        "arn:aws:iam::123456789012:user/custom",
        "arn:aws:iam::123456789012:user/bob",
    }


def test_iam_inventory_guard_accepts_provisioned_users(mocker: MockerFixture) -> None:
    inventory = mocker.Mock()
    inventory.list_users.return_value = [
        AWSUser(UserName=name, UserId=f"id-{name}", Arn=f"arn/{name}", Path="/")
        for name in ("alice", "bob")
    ]
    infrastructure._require_iam_users(
        inventory, account_name="account", usernames=["alice"]
    )
    inventory.list_users.assert_called_once_with()


def test_iam_inventory_guard_rejects_missing_users(mocker: MockerFixture) -> None:
    inventory = mocker.Mock()
    inventory.list_users.return_value = [
        AWSUser(UserName="alice", UserId="id-alice", Arn="arn/alice", Path="/")
    ]
    with pytest.raises(infrastructure.MissingIamUsersError, match="bob"):
        infrastructure._require_iam_users(
            inventory, account_name="account", usernames=["alice", "bob"]
        )


def test_empty_membership_does_not_require_iam_inventory(mocker: MockerFixture) -> None:
    inventory = mocker.Mock()
    infrastructure._require_iam_users(inventory, account_name="account", usernames=[])
    inventory.list_users.assert_not_called()
