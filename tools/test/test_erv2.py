from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.gql_definitions.external_resources.external_resources_namespaces import (
    AWSAccountV1,
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceCloudWatchV1,
    NamespaceV1,
)
from tools.cli_commands.erv2 import Erv2Cli, TfResource, TfResourceList

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.parametrize("bindings", [1, 2])
def test_erv2_counts_namespace_bindings_before_inventory_deduplication(
    mocker: MockerFixture, bindings: int
) -> None:
    resource = mocker.Mock(
        spec=NamespaceTerraformResourceCloudWatchV1,
        provider="cloudwatch",
        identifier="test-cw",
        managed_by_erv2=True,
    )
    account = mocker.Mock(spec=AWSAccountV1)
    account.name = "test-account"
    provider = mocker.Mock(
        spec=NamespaceTerraformProviderResourceAWSV1,
        provider="aws",
        provisioner=account,
        resources=[resource],
    )
    namespaces = [
        mocker.Mock(
            spec=NamespaceV1,
            managed_external_resources=True,
            external_resources=[provider],
        )
        for _ in range(bindings)
    ]
    mocker.patch("tools.cli_commands.erv2.get_namespaces", return_value=namespaces)
    for name in (
        "ExternalResourcesInventory",
        "get_settings",
        "get_modules",
        "load_module_inventory",
        "setup_factories",
        "ExternalResourceModuleConfiguration.resolve_configuration",
    ):
        mocker.patch(f"tools.cli_commands.erv2.{name}")

    cli = Erv2Cli("aws", "test-account", "cloudwatch", "test-cw", mocker.Mock())

    assert cli.resource_bindings_count == bindings


def test_erv2_reconcile_does_not_scan_state_table(mocker: MockerFixture) -> None:
    mocker.patch("tools.cli_commands.erv2.gql.get_api")
    api = mocker.patch(
        "tools.cli_commands.erv2.get_aws_api"
    ).return_value.__enter__.return_value
    client = api.dynamodb.boto3_client
    client.get_item.return_value = {}
    client.get_paginator.side_effect = AssertionError("A point update must not scan")
    cli = Erv2Cli.__new__(Erv2Cli)
    cli._provision_provider = "aws"
    cli._provisioner = "test-account"
    cli._provider = "cloudwatch"
    cli._identifier = "test-cw"
    cli._secret_reader = mocker.Mock()
    cli._er_settings = mocker.Mock(state_dynamodb_table="test-state")

    cli.reconcile()

    client.get_item.assert_called_once_with(
        TableName="test-state",
        ConsistentRead=True,
        Key={
            "external_resource_key_hash": {"S": "aws/test-account/cloudwatch/test-cw"}
        },
    )
    client.get_paginator.assert_not_called()
    client.update_item.assert_not_called()


def test_erv2_model_tfresource_list() -> None:
    # terraform_resource_list
    terraform_resource_list = TfResourceList(
        resources=[
            TfResource(address="postfix-module.user-1"),
            TfResource(address="postfix-module.user-2"),
            TfResource(address="prefix-module.user-1"),
            TfResource(address="prefix-module.user-2"),
            TfResource(address="exact-module.identifier"),
            TfResource(address="something.else"),
            # real life examples
            TfResource(
                address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage"
            ),
            TfResource(
                address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user"
            ),
            TfResource(address="aws_secretsmanager_secret.playground-user"),
            TfResource(address="aws_secretsmanager_secret.foobar-playground-user"),
        ]
    )
    assert len(terraform_resource_list) == 10
    # exact match
    assert terraform_resource_list[TfResource(address="exact-module.identifier")] == [
        TfResource(address="exact-module.identifier")
    ]
    # with postfix
    assert terraform_resource_list[
        TfResource(address="postfix-module.user-1-postfix")
    ] == [TfResource(address="postfix-module.user-1")]
    # with prefix
    assert terraform_resource_list[
        TfResource(address="prefix-module.prefix-user-1")
    ] == [TfResource(address="prefix-module.user-1")]

    # real life examples
    assert terraform_resource_list[
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-secret"
        )
    ] == [
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage"
        ),
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user"
        ),
    ]
    assert terraform_resource_list[
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user-secret"
        )
    ] == [
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage"
        ),
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user"
        ),
    ]

    assert terraform_resource_list[
        TfResource(address="aws_secretsmanager_secret.secret-foobar-playground-user")
    ] == [
        TfResource(address="aws_secretsmanager_secret.playground-user"),
        TfResource(address="aws_secretsmanager_secret.foobar-playground-user"),
    ]
    with pytest.raises(KeyError):
        # unknown resource type
        terraform_resource_list[TfResource(address="not.found")]

    assert (
        terraform_resource_list[TfResource(address="aws_secretsmanager_secret.found")]
        == []
    )
