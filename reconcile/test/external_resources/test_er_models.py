from collections.abc import Callable

import pytest
from pytest import fixture

from reconcile.external_resources.model import (
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
