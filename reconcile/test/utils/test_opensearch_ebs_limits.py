from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from reconcile.utils.aws_api import AWSApi
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.terrascript_aws_client import TerrascriptClient

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def build_spec() -> ExternalResourceSpec:
    provisioner = {"name": "some-account"}
    resource: dict[str, Any] = {
        "identifier": "test-domain",
        "provider": "elasticsearch",
    }
    namespace = {
        "name": "test-namespace",
        "cluster": {"name": "test-cluster"},
        "environment": {"name": "test-environment"},
        "app": {"name": "test-app"},
    }
    return ExternalResourceSpec("aws", provisioner, resource, namespace)


def build_values(volume_size: int = 257, volume_type: str = "gp2") -> dict[str, Any]:
    return {
        "identifier": "test-domain",
        "tags": {},
        "elasticsearch_version": "OpenSearch_2.15",
        "ebs_options": {
            "ebs_enabled": True,
            "volume_size": volume_size,
            "volume_type": volume_type,
        },
        "cluster_config": {
            "instance_type": "m5.large.elasticsearch",
            "dedicated_master_enabled": False,
            "zone_awareness_enabled": False,
        },
        "vpc_options": {"subnet_ids": ["subnet-1"]},
        "region": "us-east-1",
    }


def build_limits() -> dict[str, Any]:
    return {
        "LimitsByRole": {
            "data": {
                "StorageTypes": [
                    {
                        "StorageTypeName": "ebs",
                        "StorageSubTypeName": "gp2",
                        "StorageTypeLimits": [
                            {
                                "LimitName": "MaximumVolumeSize",
                                "LimitValues": ["256"],
                            }
                        ],
                    },
                    {
                        "StorageTypeName": "ebs",
                        "StorageSubTypeName": "gp3",
                        "StorageTypeLimits": [
                            {
                                "LimitName": "MaximumVolumeSize",
                                "LimitValues": ["512"],
                            }
                        ],
                    },
                ]
            },
            "master": {
                "StorageTypes": [
                    {
                        "StorageTypeName": "ebs",
                        "StorageSubTypeName": "gp2",
                        "StorageTypeLimits": [
                            {
                                "LimitName": "MaximumVolumeSize",
                                "LimitValues": ["1"],
                            }
                        ],
                    }
                ]
            },
        }
    }


@pytest.fixture
def terrascript_client() -> TerrascriptClient:
    client = TerrascriptClient("", "", 1, [], default_tags=None)
    client.default_regions = {"some-account": "us-east-1"}
    return client


@pytest.mark.parametrize(
    ("volume_type", "volume_size", "expected_warning"),
    [
        ("gp2", 256, False),
        ("gp2", 257, True),
        ("gp3", 257, False),
        ("gp3", 513, True),
    ],
)
def test_warn_elasticsearch_ebs_limits_by_type_and_boundary(
    terrascript_client: TerrascriptClient,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    volume_type: str,
    volume_size: int,
    expected_warning: bool,
) -> None:
    spec = build_spec()
    values = build_values(volume_size, volume_type)
    terrascript_client.account_resource_specs = {"some-account": [spec]}
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = build_limits()

    terrascript_client.warn_elasticsearch_ebs_limits(aws_api)

    assert ("OpenSearch domain test-domain" in caplog.text) is expected_warning
    aws_api.get_opensearch_instance_type_limits.assert_called_once_with(
        "some-account", "us-east-1", "OpenSearch_2.15", "m5.large.search"
    )
    assert spec.resource == {"identifier": "test-domain", "provider": "elasticsearch"}


@pytest.mark.parametrize(
    "ebs_options",
    [
        None,
        {},
        {"ebs_enabled": False, "volume_size": 100},
        {"ebs_enabled": True},
    ],
)
def test_warn_elasticsearch_ebs_limits_skips_disabled_or_absent_ebs(
    terrascript_client: TerrascriptClient,
    mocker: MockerFixture,
    ebs_options: dict[str, Any] | None,
) -> None:
    spec = build_spec()
    values = build_values()
    values["ebs_options"] = ebs_options
    terrascript_client.account_resource_specs = {"some-account": [spec]}
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)

    terrascript_client.warn_elasticsearch_ebs_limits(aws_api)

    aws_api.get_opensearch_instance_type_limits.assert_not_called()


def test_warn_elasticsearch_ebs_limits_skips_missing_limit_and_logs(
    terrascript_client: TerrascriptClient,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    spec = build_spec()
    values = build_values()
    terrascript_client.account_resource_specs = {"some-account": [spec]}
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = {}

    terrascript_client.warn_elasticsearch_ebs_limits(aws_api)

    assert "Skipping OpenSearch EBS limit check" in caplog.text
    assert "OpenSearch domain test-domain" not in caplog.text


def test_warn_elasticsearch_ebs_limits_uses_default_instance_type(
    terrascript_client: TerrascriptClient,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")
    spec = build_spec()
    values = build_values(volume_size=36)
    values.pop("cluster_config")
    terrascript_client.account_resource_specs = {"some-account": [spec]}
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    limits = build_limits()
    limits["LimitsByRole"]["data"]["StorageTypes"][0]["StorageTypeLimits"][0][
        "LimitValues"
    ] = ["35"]
    aws_api.get_opensearch_instance_type_limits.return_value = limits

    terrascript_client.warn_elasticsearch_ebs_limits(aws_api)

    aws_api.get_opensearch_instance_type_limits.assert_called_once_with(
        "some-account", "us-east-1", "OpenSearch_2.15", "t2.small.search"
    )
    assert "OpenSearch domain test-domain" in caplog.text


def test_warn_elasticsearch_ebs_limits_skips_unknown_volume_type(
    terrascript_client: TerrascriptClient,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    spec = build_spec()
    values = build_values(volume_type="io2")
    terrascript_client.account_resource_specs = {"some-account": [spec]}
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = build_limits()

    terrascript_client.warn_elasticsearch_ebs_limits(aws_api)

    assert "Skipping OpenSearch EBS limit check" in caplog.text
    assert "OpenSearch domain test-domain" not in caplog.text


def test_warn_elasticsearch_ebs_limits_skips_missing_engine_version(
    terrascript_client: TerrascriptClient,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    spec = build_spec()
    values = build_values()
    values["elasticsearch_version"] = None
    terrascript_client.account_resource_specs = {"some-account": [spec]}
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)

    terrascript_client.warn_elasticsearch_ebs_limits(aws_api)

    aws_api.get_opensearch_instance_type_limits.assert_not_called()
    assert "engine version or region is not configured" in caplog.text


def test_warn_elasticsearch_ebs_limits_does_not_change_generated_resource(
    terrascript_client: TerrascriptClient,
    mocker: MockerFixture,
) -> None:
    spec = build_spec()
    values = build_values()
    original_resource = dict(spec.resource)
    terrascript_client.account_resource_specs = {"some-account": [spec]}
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    mocker.patch.object(terrascript_client, "init_common_outputs")
    mocker.patch.object(
        terrascript_client,
        "_get_tf_resource_elasticsearch_log_groups",
        return_value=([], {}),
    )
    mocker.patch.object(
        terrascript_client, "_get_elasticsearch_account_wide_resource_policy"
    )
    mocker.patch.object(
        terrascript_client, "get_elasticsearch_service_role_tf_resource"
    )
    mocker.patch.object(terrascript_client, "get_dependencies", return_value=[])
    add_resources = mocker.patch.object(terrascript_client, "add_resources")
    es_resource = mocker.Mock()
    es_resource.arn = "arn"
    es_resource.domain_id = "domain-id"
    es_resource.domain_name = "domain-name"
    es_resource.endpoint = "endpoint"
    es_resource.kibana_endpoint = "kibana-endpoint"
    build_elasticsearch_domain = mocker.patch(
        "reconcile.utils.terrascript_aws_client.aws_elasticsearch_domain",
        return_value=es_resource,
    )
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = build_limits()

    terrascript_client.warn_elasticsearch_ebs_limits(aws_api)
    terrascript_client.populate_tf_resource_elasticsearch(spec)

    generated_resources = add_resources.call_args.args[1]
    assert spec.resource == original_resource
    assert build_elasticsearch_domain.call_args.kwargs["ebs_options"] == {
        "ebs_enabled": True,
        "volume_size": 257,
        "volume_type": "gp2",
        "iops": 0,
    }
    assert values["ebs_options"] == {
        "ebs_enabled": True,
        "volume_size": 257,
        "volume_type": "gp2",
    }
    assert any(resource is es_resource for resource in generated_resources)
