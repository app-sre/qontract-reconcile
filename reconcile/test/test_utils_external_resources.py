import pytest
from reconcile.utils.external_resource_spec import ExternalResourceSpec

import reconcile.utils.external_resources as uer


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
