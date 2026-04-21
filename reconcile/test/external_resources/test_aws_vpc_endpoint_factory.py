from unittest.mock import Mock

import pytest

from reconcile.external_resources.aws import AWSVpcEndpointFactory
from reconcile.external_resources.model import ExternalResourceModuleConfiguration
from reconcile.utils.external_resource_spec import ExternalResourceSpec


@pytest.fixture
def module_conf() -> ExternalResourceModuleConfiguration:
    return ExternalResourceModuleConfiguration(
        image="stable-image",
        version="1.0.0",
        outputs_secret_image="path/to/er-output-secret-image",
        outputs_secret_version="er-output-secret-version",
        reconcile_timeout_minutes=60,
        reconcile_drift_interval_minutes=60,
    )


def _make_spec(vpc: dict) -> ExternalResourceSpec:
    return ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "test", "resources_default_region": "us-east-1"},
        resource={
            "identifier": "myservice-endpoint",
            "provider": "vpc-endpoint",
            "endpoint_service_name": "com.amazonaws.vpce.us-east-1.vpce-svc-0123456789abcdef0",
            "vpc": vpc,
        },
        namespace={
            "cluster": {"name": "test_cluster"},
            "name": "test_namespace",
            "environment": {"name": "test_env"},
            "app": {"name": "test_app"},
        },
    )


def test_resolve_flattens_vpc(module_conf: ExternalResourceModuleConfiguration) -> None:
    spec = _make_spec({
        "vpc_id": "vpc-0123456789abcdef0",
        "region": "us-east-1",
        "subnets": [
            {"id": "subnet-aaaa", "privacy": "private"},
            {"id": "subnet-bbbb", "privacy": "private"},
            {"id": "subnet-cccc", "privacy": "public"},
        ],
    })
    factory = AWSVpcEndpointFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert data["vpc_id"] == "vpc-0123456789abcdef0"
    assert data["region"] == "us-east-1"
    assert data["subnet_ids"] == ["subnet-aaaa", "subnet-bbbb"]
    assert "vpc" not in data


def test_resolve_private_subnets_only(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec({
        "vpc_id": "vpc-abc",
        "subnets": [
            {"id": "subnet-pub1", "privacy": "public"},
            {"id": "subnet-priv1", "privacy": "private"},
            {"id": "subnet-noprivacy"},
        ],
    })
    factory = AWSVpcEndpointFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert data["subnet_ids"] == ["subnet-priv1"]


def test_resolve_no_region_in_vpc(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec({
        "vpc_id": "vpc-abc",
        "subnets": [],
    })
    factory = AWSVpcEndpointFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert "region" not in data


def test_resolve_empty_subnets(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec({
        "vpc_id": "vpc-abc",
        "region": "us-east-1",
        "subnets": [],
    })
    factory = AWSVpcEndpointFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert data["subnet_ids"] == []


def test_resolve_passes_through_endpoint_service_name(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec({
        "vpc_id": "vpc-abc",
        "subnets": [],
    })
    factory = AWSVpcEndpointFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert (
        data["endpoint_service_name"]
        == "com.amazonaws.vpce.us-east-1.vpce-svc-0123456789abcdef0"
    )
