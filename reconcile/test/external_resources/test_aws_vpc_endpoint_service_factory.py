from unittest.mock import Mock

import pytest

from reconcile.external_resources.aws import AWSVpcEndpointServiceFactory
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


def _make_spec(
    allowed_consumer_clusters: list | None = None,
    allowed_principal_arns: list | None = None,
) -> ExternalResourceSpec:
    resource: dict = {
        "identifier": "vault-stage-vpce-service",
        "provider": "vpc-endpoint-service",
        "openshift_service_name": "vault",
    }
    if allowed_consumer_clusters is not None:
        resource["allowed_consumer_clusters"] = allowed_consumer_clusters
    if allowed_principal_arns is not None:
        resource["allowed_principal_arns"] = allowed_principal_arns
    return ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "test", "resources_default_region": "us-east-1"},
        resource=resource,
        namespace={
            "cluster": {"name": "test_cluster"},
            "name": "test_namespace",
            "environment": {"name": "test_env"},
            "app": {"name": "test_app"},
        },
    )


def _cluster(uid: str, terraform_username: str) -> dict:
    return {
        "name": f"cluster-{uid}",
        "spec": {"account": {"uid": uid, "terraformUsername": terraform_username}},
    }


def test_resolve_builds_arns_from_clusters(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec(
        allowed_consumer_clusters=[
            _cluster("111111111111", "cluster-a-terraform"),
            _cluster("222222222222", "cluster-b-terraform"),
        ]
    )
    factory = AWSVpcEndpointServiceFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert data["allowed_principal_arns"] == [
        "arn:aws:iam::111111111111:user/cluster-a-terraform",
        "arn:aws:iam::222222222222:user/cluster-b-terraform",
    ]
    assert "allowed_consumer_clusters" not in data


def test_resolve_passes_through_explicit_arns(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec(allowed_principal_arns=["arn:aws:iam::536697226309:root"])
    factory = AWSVpcEndpointServiceFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert data["allowed_principal_arns"] == ["arn:aws:iam::536697226309:root"]


def test_resolve_merges_cluster_arns_and_explicit_arns(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec(
        allowed_consumer_clusters=[_cluster("111111111111", "cluster-a-terraform")],
        allowed_principal_arns=["arn:aws:iam::536697226309:root"],
    )
    factory = AWSVpcEndpointServiceFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert data["allowed_principal_arns"] == [
        "arn:aws:iam::111111111111:user/cluster-a-terraform",
        "arn:aws:iam::536697226309:root",
    ]


def test_resolve_empty_when_no_arns_configured(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec()
    factory = AWSVpcEndpointServiceFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert data["allowed_principal_arns"] == []


def test_resolve_skips_cluster_without_account(
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    spec = _make_spec(
        allowed_consumer_clusters=[
            _cluster("111111111111", "cluster-a-terraform"),
            {"name": "broken-cluster", "spec": {}},
        ]
    )
    factory = AWSVpcEndpointServiceFactory(Mock(), Mock())

    data = factory.resolve(spec, module_conf)

    assert data["allowed_principal_arns"] == [
        "arn:aws:iam::111111111111:user/cluster-a-terraform",
    ]
