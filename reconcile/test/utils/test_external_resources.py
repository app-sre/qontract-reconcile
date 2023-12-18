import json
from collections import Counter

import pytest

import reconcile.utils.external_resources as uer
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
    ExternalResourceUniqueKey,
)


@pytest.fixture
def namespace_info():
    return {
        "managedExternalResources": True,
        "externalResources": [
            {
                "provider": uer.PROVIDER_AWS,
                "provisioner": {
                    "name": "acc1",
                },
                "resources": [
                    {
                        "provider": "rds",
                    }
                ],
            },
            {
                "provider": uer.PROVIDER_AWS,
                "provisioner": {
                    "name": "acc2",
                },
                "resources": [
                    {
                        "provider": "rds",
                    }
                ],
            },
            {
                "provider": "other",
                "provisioner": {
                    "name": "acc3",
                },
                "resources": [
                    {
                        "provider": "other",
                    }
                ],
            },
        ],
    }


@pytest.fixture
def expected(namespace_info):
    return [
        ExternalResourceSpec(
            provision_provider=uer.PROVIDER_AWS,
            resource={"provider": "rds"},
            provisioner={"name": "acc1"},
            namespace=namespace_info,
        ),
        ExternalResourceSpec(
            provision_provider=uer.PROVIDER_AWS,
            resource={"provider": "rds"},
            provisioner={"name": "acc2"},
            namespace=namespace_info,
        ),
    ]


def test_get_external_resource_specs(namespace_info, expected):
    results = uer.get_external_resource_specs(
        namespace_info, provision_provider=uer.PROVIDER_AWS
    )
    assert results == expected


@pytest.fixture
def expected_other(namespace_info):
    return [
        ExternalResourceSpec(
            provision_provider="other",
            resource={"provider": "other"},
            provisioner={"name": "acc3"},
            namespace=namespace_info,
        ),
    ]


def test_get_external_resource_specs_no_filter(
    namespace_info, expected, expected_other
):
    results = uer.get_external_resource_specs(namespace_info)
    assert results == expected + expected_other


def test_get_external_resource_specs_filter_other(namespace_info, expected_other):
    results = uer.get_external_resource_specs(
        namespace_info, provision_provider="other"
    )
    assert results == expected_other


def test_get_provision_providers(namespace_info):
    results = uer.get_provision_providers(namespace_info)
    assert results == {uer.PROVIDER_AWS, "other"}


def test_get_provision_providers_none():
    namespace_info = {"managedExternalResources": False}
    results = uer.get_provision_providers(namespace_info)
    assert not results


def test_managed_external_resources():
    namespace_info = {"managedExternalResources": True}
    assert uer.managed_external_resources(namespace_info) is True


def test_managed_external_resources_none():
    namespace_info = {"managedExternalResources": False}
    assert uer.managed_external_resources(namespace_info) is False


def test_resource_value_resolver_no_defaults_or_overrides():
    """Values are resolved properly when defaults and overrides are omitted."""
    spec = ExternalResourceSpec(
        provision_provider="other",
        provisioner={"name": "some_account"},
        resource={
            "provider": "other",
            "identifier": "some-id",
            "field_1": "data1",
            "field_2": "data2",
            "field_3": "data3",
        },
        namespace={},
    )

    resolver = uer.ResourceValueResolver(spec)
    values = resolver.resolve()

    assert values == {"field_1": "data1", "field_2": "data2", "field_3": "data3"}


def test_resource_value_resolver_identifier_as_value():
    """
    `identifier` is added to the resolved values if `identifier_as_value` is set. This
    is for compatibility when both our schemas and a Terraform provider both expect
    `identifier` to be present (so it must be in the resolved values).
    """
    spec = ExternalResourceSpec(
        provision_provider="other",
        provisioner={"name": "some_account"},
        resource={
            "provider": "other",
            "identifier": "some-id",
            "field_1": "data1",
            "field_2": "data2",
            "field_3": "data3",
        },
        namespace={},
    )

    resolver = uer.ResourceValueResolver(spec, identifier_as_value=True)
    values = resolver.resolve()

    assert values == {
        "identifier": "some-id",
        "field_1": "data1",
        "field_2": "data2",
        "field_3": "data3",
    }


def test_resource_value_resolver_tags():
    """`tags` is added to the resolved values if `integration_tag` is set."""
    spec = ExternalResourceSpec(
        provision_provider="other",
        provisioner={"name": "some_account"},
        resource={
            "provider": "other",
            "identifier": "some-id",
            "field_1": "data1",
            "field_2": "data2",
            "field_3": "data3",
        },
        namespace={
            "name": "some-namespace",
            "cluster": {"name": "some-cluster"},
            "environment": {"name": "some-name"},
            "app": {"name": "some-app"},
        },
    )

    resolver = uer.ResourceValueResolver(spec, integration_tag="some-integration")
    values = resolver.resolve()

    assert values == {
        "field_1": "data1",
        "field_2": "data2",
        "field_3": "data3",
        "tags": {
            "app": "some-app",
            "cluster": "some-cluster",
            "environment": "some-name",
            "managed_by_integration": "some-integration",
            "namespace": "some-namespace",
        },
    }


def test_resource_value_resolver_overrides_and_defaults(mocker):
    """Values are resolved properly when overrides and defaults exist."""
    # The need to patch here will go away once we start using the resolveResource
    # schema option.
    patch_get_values = mocker.patch.object(uer.ResourceValueResolver, "_get_values")
    patch_get_values.return_value = {
        "default_1": "default_data1",
        "default_2": "default_data2",
        "default_3": "default_data3",
    }

    spec = ExternalResourceSpec(
        provision_provider="other",
        provisioner={"name": "some_account"},
        resource={
            "provider": "other",
            "identifier": "some-id",
            "field_1": "field_data1",
            "field_2": "field_data2",
            "field_3": "field_data3",
            "overrides": json.dumps({"default_2": "override_data2"}),
            "defaults": "/some/path",
        },
        namespace={},
    )

    resolver = uer.ResourceValueResolver(spec)
    values = resolver.resolve()

    assert values == {
        "field_1": "field_data1",
        "field_2": "field_data2",
        "field_3": "field_data3",
        "default_1": "default_data1",
        "default_2": "override_data2",
        "default_3": "default_data3",
    }


def test_get_inventory_count_combinations():
    inventory: ExternalResourceSpecInventory = {}
    inventory[
        ExternalResourceUniqueKey("pp1", "pn1", "id1", "rds")
    ] = ExternalResourceSpec("pp1", {}, {}, {})
    inventory[
        ExternalResourceUniqueKey("pp1", "pn1", "id2", "rds")
    ] = ExternalResourceSpec("pp1", {}, {}, {})
    inventory[
        ExternalResourceUniqueKey("pp2", "pn2", "id3", "rds")
    ] = ExternalResourceSpec("pp2", {}, {}, {})
    inventory[
        ExternalResourceUniqueKey("pp2", "pn3", "id4", "s3")
    ] = ExternalResourceSpec("pp2", {}, {}, {})
    inventory[
        ExternalResourceUniqueKey("pp3", "pn4", "id5", "s3")
    ] = ExternalResourceSpec("pp3", {}, {}, {})
    inventory[
        ExternalResourceUniqueKey("pp3", "pn4", "id6", "asg")
    ] = ExternalResourceSpec("pp3", {}, {}, {})

    count_combinations = uer.get_inventory_count_combinations(inventory)
    expected_count_combinations = Counter({
        ("pp1", "pn1", "rds"): 2,
        ("pp2", "pn2", "rds"): 1,
        ("pp2", "pn3", "s3"): 1,
        ("pp3", "pn4", "s3"): 1,
        ("pp3", "pn4", "asg"): 1,
    })
    assert expected_count_combinations == count_combinations
