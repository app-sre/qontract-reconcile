from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from reconcile.utils.aws_api import AWSApi
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.terrascript_aws_client import TerrascriptClient

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def build_spec(identifier: str = "test-domain") -> ExternalResourceSpec:
    provisioner = {"name": "some-account"}
    resource: dict[str, Any] = {
        "identifier": identifier,
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


@dataclass
class PopulateMocks:
    add_resources: Any
    build_elasticsearch_domain: Any
    es_resource: Any


@pytest.fixture
def terrascript_client() -> TerrascriptClient:
    client = TerrascriptClient("", "", 1, [], default_tags=None)
    client.default_regions = {"some-account": "us-east-1"}
    return client


@pytest.fixture
def populate_mocks(
    terrascript_client: TerrascriptClient, mocker: MockerFixture
) -> PopulateMocks:
    """Stub Terraform resource plumbing so tests only exercise the EBS check."""
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
    return PopulateMocks(add_resources, build_elasticsearch_domain, es_resource)


@pytest.mark.parametrize(
    ("volume_type", "volume_size", "expected_warning"),
    [
        ("gp2", 256, False),
        ("gp2", 257, True),
        ("gp3", 257, False),
        ("gp3", 513, True),
    ],
)
def test_warns_by_volume_type_and_boundary(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    volume_type: str,
    volume_size: int,
    expected_warning: bool,
) -> None:
    spec = build_spec()
    values = build_values(volume_size, volume_type)
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = build_limits()

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    assert ("OpenSearch domain test-domain" in caplog.text) is expected_warning
    aws_api.get_opensearch_instance_type_limits.assert_called_once_with(
        "some-account", "us-east-1", "OpenSearch_2.15", "m5.large.search"
    )
    assert spec.resource == {"identifier": "test-domain", "provider": "elasticsearch"}


@pytest.mark.parametrize(
    ("configured_version", "api_version"),
    [
        ("7.10", "Elasticsearch_7.10"),
        ("Elasticsearch_7.10", "Elasticsearch_7.10"),
        ("OpenSearch_2.15", "OpenSearch_2.15"),
    ],
)
def test_normalizes_engine_version_for_api_only(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    configured_version: str,
    api_version: str,
) -> None:
    spec = build_spec()
    values = build_values()
    values["elasticsearch_version"] = configured_version
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = build_limits()

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    aws_api.get_opensearch_instance_type_limits.assert_called_once_with(
        "some-account", "us-east-1", api_version, "m5.large.search"
    )
    assert values["elasticsearch_version"] == configured_version
    assert (
        populate_mocks.build_elasticsearch_domain.call_args.kwargs[
            "elasticsearch_version"
        ]
        == configured_version
    )


@pytest.mark.parametrize(
    "ebs_options",
    [
        None,
        {},
        {"ebs_enabled": False, "volume_size": 100},
    ],
)
def test_skips_disabled_or_absent_ebs(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    ebs_options: dict[str, Any] | None,
) -> None:
    spec = build_spec()
    values = build_values()
    values["ebs_options"] = ebs_options
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    aws_api.get_opensearch_instance_type_limits.assert_not_called()


def test_missing_volume_size_raises_before_lookup(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
) -> None:
    spec = build_spec()
    values = build_values()
    values["ebs_options"] = {"ebs_enabled": True}
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)

    with pytest.raises(ValueError, match="volume_size is required"):
        terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    aws_api.get_opensearch_instance_type_limits.assert_not_called()


def test_skips_when_aws_returns_no_limits(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")
    spec = build_spec()
    mocker.patch.object(terrascript_client, "init_values", return_value=build_values())
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = None

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    assert "OpenSearch domain test-domain" not in caplog.text


def test_skips_missing_limit_and_logs(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    spec = build_spec()
    mocker.patch.object(terrascript_client, "init_values", return_value=build_values())
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = {}

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    assert "Skipping OpenSearch EBS limit check" in caplog.text
    assert "OpenSearch domain test-domain" not in caplog.text


def test_uses_default_instance_type(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")
    spec = build_spec()
    values = build_values(volume_size=36)
    # No instance_type configured, so the default applies.
    values["cluster_config"] = {
        "dedicated_master_enabled": False,
        "zone_awareness_enabled": False,
    }
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    limits = build_limits()
    limits["LimitsByRole"]["data"]["StorageTypes"][0]["StorageTypeLimits"][0][
        "LimitValues"
    ] = ["35"]
    aws_api.get_opensearch_instance_type_limits.return_value = limits

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    aws_api.get_opensearch_instance_type_limits.assert_called_once_with(
        "some-account", "us-east-1", "OpenSearch_2.15", "t2.small.search"
    )
    assert "OpenSearch domain test-domain" in caplog.text


def test_skips_unknown_volume_type(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    spec = build_spec()
    mocker.patch.object(
        terrascript_client,
        "init_values",
        return_value=build_values(volume_type="io2"),
    )
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = build_limits()

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    assert "Skipping OpenSearch EBS limit check" in caplog.text
    assert "OpenSearch domain test-domain" not in caplog.text


def test_skips_missing_engine_version(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    spec = build_spec()
    values = build_values()
    values["elasticsearch_version"] = None
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    aws_api.get_opensearch_instance_type_limits.assert_not_called()
    assert "engine version is not configured" in caplog.text


def test_does_not_change_generated_resource(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
) -> None:
    spec = build_spec()
    values = build_values()
    original_resource = dict(spec.resource)
    mocker.patch.object(terrascript_client, "init_values", return_value=values)
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = build_limits()

    terrascript_client.populate_tf_resource_elasticsearch(spec, aws_api=aws_api)

    generated_resources = populate_mocks.add_resources.call_args.args[1]
    assert spec.resource == original_resource
    assert populate_mocks.build_elasticsearch_domain.call_args.kwargs[
        "ebs_options"
    ] == {
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
    assert any(
        resource is populate_mocks.es_resource for resource in generated_resources
    )


def test_dedups_skip_message_for_shared_key(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    mocker.patch.object(terrascript_client, "init_values", return_value=build_values())
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = {}

    terrascript_client.populate_tf_resource_elasticsearch(
        build_spec("test-domain"), aws_api=aws_api
    )
    terrascript_client.populate_tf_resource_elasticsearch(
        build_spec("test-domain-2"), aws_api=aws_api
    )

    assert caplog.text.count("AWS did not return a maximum") == 1


def test_logs_skip_message_for_distinct_keys(
    terrascript_client: TerrascriptClient,
    populate_mocks: PopulateMocks,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    other_region_values = build_values()
    other_region_values["region"] = "us-west-2"
    mocker.patch.object(
        terrascript_client,
        "init_values",
        side_effect=[build_values(), other_region_values],
    )
    aws_api = mocker.create_autospec(AWSApi, instance=True)
    aws_api.get_opensearch_instance_type_limits.return_value = {}

    terrascript_client.populate_tf_resource_elasticsearch(
        build_spec("test-domain"), aws_api=aws_api
    )
    terrascript_client.populate_tf_resource_elasticsearch(
        build_spec("test-domain-2"), aws_api=aws_api
    )

    assert caplog.text.count("AWS did not return a maximum") == 2


def test_populate_resources_resets_reported_skips(
    terrascript_client: TerrascriptClient,
    mocker: MockerFixture,
) -> None:
    terrascript_client.account_resource_specs = {}
    terrascript_client._reported_elasticsearch_ebs_limit_skips.add(("stale",))
    mocker.patch.object(terrascript_client, "populate_tf_resources")
    aws_api = mocker.create_autospec(AWSApi, instance=True)

    terrascript_client.populate_resources(aws_api=aws_api)

    assert terrascript_client._reported_elasticsearch_ebs_limit_skips == set()
