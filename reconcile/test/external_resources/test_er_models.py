from collections.abc import Callable

import pytest
from pytest import fixture

from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceKey,
    ExternalResourcesInventory,
)
from reconcile.typed_queries.external_resources import NamespaceV1


@fixture
def namespaces(gql_class_factory: Callable[..., NamespaceV1]) -> list[NamespaceV1]:
    common_attrs = {
        "environment": {"name": "env", "labels": "", "servicePhase": "dev"},
        "app": {
            "path": "app.yml",
            "name": "app",
            "appCode": "1",
            "costCenter": "1",
        },
        "cluster": {
            "name": "cluster-01",
            "serverUrl": "https://example.com",
        },
    }
    return [
        gql_class_factory(
            NamespaceV1,
            {
                **common_attrs,
                "name": "namespace-01",
                "delete": False,
                "managedExternalResources": True,
                "externalResources": [
                    {
                        "provider": "aws",
                        "provisioner": {
                            "name": "aws-account",
                            "resourcesDefaultRegion": "us-east-1",
                        },
                        "resources": [
                            # ExternalResourceKey(provision_provider='aws', provisioner_name='aws-account', provider='whatever', identifier='res-01')
                            {
                                "identifier": "res-01",
                                "provider": "whatever",
                                "managed_by_erv2": True,
                            },
                            # ExternalResourceKey(provision_provider='aws', provisioner_name='aws-account', provider='whatever', identifier='res-02')
                            {
                                "identifier": "res-02",
                                "provider": "whatever",
                                "managed_by_erv2": True,
                            },
                            # ExternalResourceKey(provision_provider='aws', provisioner_name='aws-account', provider='whatever', identifier='deleted-res')
                            {
                                "identifier": "deleted-res",
                                "provider": "whatever",
                                "managed_by_erv2": True,
                                "delete": True,
                            },
                            # must be ignored - not managed by ERv2
                            {
                                "identifier": "not-erv2",
                                "provider": "whatever",
                                "managed_by_erv2": False,
                            },
                        ],
                    },
                ],
            },
        ),
        # deleted namespace
        gql_class_factory(
            NamespaceV1,
            {
                **common_attrs,
                "name": "deleted-namespace",
                "delete": True,
                "managedExternalResources": True,
                "externalResources": [
                    {
                        "provider": "aws",
                        "provisioner": {
                            "name": "aws-account",
                            "resourcesDefaultRegion": "us-east-1",
                        },
                        "resources": [
                            # ExternalResourceKey(provision_provider='aws', provisioner_name='aws-account', provider='whatever', identifier='namespace-deleted-res-01')
                            {
                                "identifier": "namespace-deleted-res-01",
                                "provider": "whatever",
                                "managed_by_erv2": True,
                            },
                            # ExternalResourceKey(provision_provider='aws', provisioner_name='aws-account', provider='whatever', identifier='namespace-deleted-res-02')
                            {
                                "identifier": "namespace-deleted-res-02",
                                "provider": "whatever",
                                "managed_by_erv2": True,
                            },
                            # ExternalResourceKey(provision_provider='aws', provisioner_name='aws-account', provider='whatever', identifier='namespace-deleted-deleted-res')
                            {
                                "identifier": "namespace-deleted-deleted-res",
                                "provider": "whatever",
                                "managed_by_erv2": True,
                                "delete": True,
                            },
                        ],
                    },
                ],
            },
        ),
        # unmanaged external resources
        gql_class_factory(
            NamespaceV1,
            {
                **common_attrs,
                "name": "unmanaged-external-resources",
                "delete": False,
                "managedExternalResources": False,
                "externalResources": [
                    {
                        "provider": "aws",
                        "provisioner": {
                            "name": "aws-account",
                            "resourcesDefaultRegion": "us-east-1",
                        },
                        "resources": [
                            {
                                "identifier": "unmanaged-external-resources-res-01",
                                "provider": "whatever",
                                "managed_by_erv2": True,
                            },
                        ],
                    },
                ],
            },
        ),
    ]


@fixture
def er_inventory(
    namespaces: list[NamespaceV1],
) -> ExternalResourcesInventory:
    return ExternalResourcesInventory(namespaces)


def test_er_inventory_no_unmanaged_resource(
    er_inventory: ExternalResourcesInventory,
) -> None:
    assert len(er_inventory) == 6


@pytest.mark.parametrize(
    "identifier, expected_delete_flag",
    [
        ("res-01", False),
        ("res-02", False),
        ("deleted-res", True),
        ("namespace-deleted-res-01", True),
        ("namespace-deleted-res-02", True),
        ("namespace-deleted-deleted-res", True),
    ],
)
def test_er_inventory_delete_flag(
    er_inventory: ExternalResourcesInventory,
    identifier: str,
    expected_delete_flag: bool,
) -> None:
    item = er_inventory.get(
        ExternalResourceKey(
            provision_provider="aws",
            provisioner_name="aws-account",
            provider="whatever",
            identifier=identifier,
        )
    )
    assert item is not None
    assert item.marked_to_delete == expected_delete_flag


def test_er_external_resource_export(
    er_inventory: ExternalResourcesInventory,
) -> None:
    item = ExternalResource(**{
        "data": {
            "identifier": "test-rds",
            "output_prefix": "test-rds-rds",
            "timeouts": {"create": "55m", "update": "55m", "delete": "55m"},
            "tags": {
                "managed_by_integration": "external_resources",
                "cluster": "test_cluster",
                "namespace": "test_namespace",
                "environment": "test_env",
                "env": "test",
                "app": "test_app",
            },
            "region": "us-east-1",
        },
        "provision": {
            "provision_provider": "aws",
            "provisioner": "test",
            "provider": "rds",
            "identifier": "test-rds",
            "target_cluster": "test_cluster",
            "target_namespace": "test_namespace",
            "target_secret_name": "test-rds-rds",
            "module_provision_data": {
                "tf_state_bucket": "tf_state_bucket",
                "tf_state_region": "tf_state_region",
                "tf_state_dynamodb_table": "tf_state_dynamodb_table",
                "tf_state_key": "aws/test/rds/test-rds/terraform.tfstate",
            },
        },
    })
    assert item is not None
    assert (
        item.export(indent=2)  # indent for readability in test
        == """{
  "data": {
    "identifier": "test-rds",
    "output_prefix": "test-rds-rds",
    "region": "us-east-1",
    "tags": {
      "app": "test_app",
      "cluster": "test_cluster",
      "env": "test",
      "environment": "test_env",
      "managed_by_integration": "external_resources",
      "namespace": "test_namespace"
    },
    "timeouts": {
      "create": "55m",
      "delete": "55m",
      "update": "55m"
    }
  },
  "provision": {
    "identifier": "test-rds",
    "module_provision_data": {
      "tf_state_bucket": "tf_state_bucket",
      "tf_state_dynamodb_table": "tf_state_dynamodb_table",
      "tf_state_key": "aws/test/rds/test-rds/terraform.tfstate",
      "tf_state_region": "tf_state_region"
    },
    "provider": "rds",
    "provision_provider": "aws",
    "provisioner": "test",
    "target_cluster": "test_cluster",
    "target_namespace": "test_namespace",
    "target_secret_name": "test-rds-rds"
  }
}"""
    )
