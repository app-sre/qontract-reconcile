import os
from typing import Any, Iterable, Mapping
import pytest

import reconcile.integrations_manager as intop
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.runtime.meta import IntegrationMeta


def test_construct_values_file_empty():
    integrations_specs: list[dict[str, Any]] = []
    expected: dict[str, list] = {
        "integrations": [],
        "cronjobs": [],
    }
    values = intop.construct_values_file(integrations_specs)
    assert values == expected


def test_construct_values_file():
    integrations_specs: list[dict[str, Any]] = [
        {
            "name": "integ1",
        },
        {
            "name": "cron1",
            "cron": "yup",
        },
    ]
    expected = {
        "integrations": [
            {"name": "integ1"},
        ],
        "cronjobs": [
            {"name": "cron1", "cron": "yup"},
        ],
    }
    values = intop.construct_values_file(integrations_specs)
    assert values == expected


def test_collect_parameters():
    template = {
        "parameters": [
            {
                "name": "tplt_param",
                "value": "default",
            }
        ]
    }
    os.environ["tplt_param"] = "override"
    environment = {
        "parameters": '{"env_param": "test"}',
    }
    parameters = intop.collect_parameters(template, environment, None)
    expected = {
        "env_param": "test",
        "tplt_param": "override",
    }
    assert parameters == expected


def test_collect_parameters_env_stronger():
    template = {
        "parameters": [
            {
                "name": "env_param",
                "value": "default",
            }
        ]
    }
    environment = {
        "parameters": '{"env_param": "override"}',
    }
    parameters = intop.collect_parameters(template, environment, None)
    expected = {
        "env_param": "override",
    }
    assert parameters == expected


def test_collect_parameters_os_env_strongest():
    template = {
        "parameters": [
            {
                "name": "env_param",
                "value": "default",
            }
        ]
    }
    os.environ["env_param"] = "strongest"
    environment = {
        "parameters": '{"env_param": "override"}',
    }
    parameters = intop.collect_parameters(template, environment, None)
    expected = {
        "env_param": "strongest",
    }
    assert parameters == expected


def test_collect_parameters_image_tag_from_ref(mocker):
    template = {
        "parameters": [
            {
                "name": "IMAGE_TAG",
                "value": "dummy",
            }
        ]
    }
    os.environ["IMAGE_TAG"] = "override"
    environment = {
        "name": "env",
        "parameters": '{"IMAGE_TAG": "default"}',
    }
    image_tag_from_ref = {"env": "f44e417"}
    mocker.patch(
        "reconcile.integrations_manager.get_image_tag_from_ref", return_value="f44e417"
    )
    parameters = intop.collect_parameters(template, environment, image_tag_from_ref)
    expected = {
        "IMAGE_TAG": "f44e417",
    }
    assert parameters == expected


@pytest.fixture
def resources() -> dict[str, Any]:
    return {
        "requests": {
            "cpu": "100m",
            "memory": "1Mi",
        },
        "limits": {
            "cpu": "100m",
            "memory": "1Mi",
        },
    }


@pytest.fixture
def integrations(resources: dict[str, Any]) -> Iterable[Mapping[str, Any]]:
    return [
        {
            "name": "integ-dont-run",
        },
        {
            "name": "integ1",
            "managed": [
                {
                    "namespace": {
                        "path": "path1",
                        "name": "ns1",
                        "cluster": {"name": "cl1"},
                        "environment": {
                            "name": "test1",
                        },
                    },
                    "spec": {"extraArgs": None, "resources": resources},
                },
            ],
        },
        {
            "name": "integ2",
            "managed": [
                {
                    "namespace": {
                        "path": "path2",
                        "name": "ns2",
                        "cluster": {"name": "cl2"},
                        "environment": {
                            "name": "test2",
                        },
                    },
                    "spec": {"extraArgs": None, "resources": resources},
                },
                {
                    "namespace": {
                        "path": "path3",
                        "name": "ns3",
                        "cluster": {"name": "cl3"},
                        "environment": {
                            "name": "test2",
                        },
                    },
                    "spec": {"extraArgs": None, "resources": resources},
                },
            ],
        },
        {
            "name": "integ3",
            "managed": [
                {
                    "namespace": {
                        "path": "path3",
                        "name": "ns3",
                        "cluster": {"name": "cl3"},
                        "environment": {
                            "name": "test2",
                        },
                    },
                    "spec": {"extraArgs": None, "resources": resources},
                },
            ],
        },
    ]


def test_collect_namespaces_single_ns(
    integrations: Iterable[Mapping[str, Any]], resources: dict[str, Any]
):
    environment_name = "test1"
    namespaces = intop.collect_namespaces(integrations, environment_name)
    expected = [
        {
            "path": "path1",
            "name": "ns1",
            "cluster": {"name": "cl1"},
            "environment": {
                "name": "test1",
            },
            "integration_specs": [
                {"name": "integ1", "resources": resources, "extraArgs": None},
            ],
        },
    ]
    assert namespaces == expected


def test_collect_namespaces_multiple_ns(
    integrations: Iterable[Mapping[str, Any]], resources: dict[str, Any]
):
    environment_name = "test2"
    namespaces = intop.collect_namespaces(integrations, environment_name)
    expected = [
        {
            "path": "path2",
            "name": "ns2",
            "cluster": {"name": "cl2"},
            "environment": {"name": "test2"},
            "integration_specs": [
                {"extraArgs": None, "resources": resources, "name": "integ2"}
            ],
        },
        {
            "path": "path3",
            "name": "ns3",
            "cluster": {"name": "cl3"},
            "environment": {"name": "test2"},
            "integration_specs": [
                {"extraArgs": None, "resources": resources, "name": "integ2"},
                {"extraArgs": None, "resources": resources, "name": "integ3"},
            ],
        },
    ]
    assert namespaces == expected


def test_collect_namespaces_all_environments(
    integrations: Iterable[Mapping[str, Any]], resources: dict[str, Any]
):
    environment_name = ""
    namespaces = intop.collect_namespaces(integrations, environment_name)
    expected = [
        {
            "path": "path1",
            "name": "ns1",
            "cluster": {"name": "cl1"},
            "environment": {
                "name": "test1",
            },
            "integration_specs": [
                {"name": "integ1", "resources": resources, "extraArgs": None},
            ],
        },
        {
            "path": "path2",
            "name": "ns2",
            "cluster": {"name": "cl2"},
            "environment": {
                "name": "test2",
            },
            "integration_specs": [
                {"name": "integ2", "resources": resources, "extraArgs": None},
            ],
        },
        {
            "path": "path3",
            "name": "ns3",
            "cluster": {"name": "cl3"},
            "environment": {"name": "test2"},
            "integration_specs": [
                {"extraArgs": None, "resources": resources, "name": "integ2"},
                {"extraArgs": None, "resources": resources, "name": "integ3"},
            ],
        },
    ]
    assert namespaces == expected


@pytest.fixture
def aws_accounts() -> list[dict[str, Any]]:
    return [
        {"name": "acc-1", "disable": None},
        {"name": "acc-2", "disable": {"integrations": None}},
        {"name": "acc-3", "disable": {"integrations": []}},
        {"name": "acc-4", "disable": {"integrations": ["integ1"]}},
    ]


@pytest.fixture
def aws_account_sharding_strategy(
    aws_accounts: list[dict[str, Any]]
) -> intop.AWSAccountShardManager:
    return intop.AWSAccountShardManager(aws_accounts)


@pytest.fixture
def shard_manager(
    aws_account_sharding_strategy: intop.AWSAccountShardManager,
) -> intop.IntegrationShardManager:
    return intop.IntegrationShardManager(
        strategies={
            "static": intop.StaticShardingStrategy(),
            "per-aws-account": aws_account_sharding_strategy,
        },
        integration_runtime_meta={
            "integ1": IntegrationMeta(
                name="integ1", short_help="", args=["--arg", "--account-name"]
            ),
            "integ2": IntegrationMeta(name="integ2", short_help="", args=["--arg"]),
            "integ3": IntegrationMeta(name="integ3", short_help="", args=[]),
        },
    )


def test_shard_manager_aws_account_filtering(
    aws_account_sharding_strategy: intop.AWSAccountShardManager,
):
    assert ["acc-1", "acc-2", "acc-3", "acc-4"] == [
        a["name"]
        for a in aws_account_sharding_strategy._aws_accounts_for_integration(
            "another-integration"
        )
    ]


def test_shard_manager_aws_account_filtering_disabled(
    aws_account_sharding_strategy: intop.AWSAccountShardManager,
):
    assert ["acc-1", "acc-2", "acc-3"] == [
        a["name"]
        for a in aws_account_sharding_strategy._aws_accounts_for_integration("integ1")
    ]


@pytest.fixture
def collected_namespaces_env_test1(
    integrations: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    return intop.collect_namespaces(integrations, "test1")


def test_initialize_shard_specs_no_shards(
    collected_namespaces_env_test1: list[dict[str, Any]],
    shard_manager: intop.IntegrationShardManager,
):
    """
    this test shows how exactly one shard is created when no sharding has been configured
    """
    intop.initialize_shard_specs(collected_namespaces_env_test1, shard_manager)
    expected = [
        {"shard_id": "0", "shards": "1", "shard_name_suffix": "", "extra_args": ""}
    ]
    assert (
        expected
        == collected_namespaces_env_test1[0]["integration_specs"][0]["shard_specs"]
    )


def test_initialize_shard_specs_two_shards(
    collected_namespaces_env_test1: list[dict[str, Any]],
    shard_manager: intop.IntegrationShardManager,
):
    """
    this test shows how the default static sharding strategy creates two shards
    """
    collected_namespaces_env_test1[0]["integration_specs"][0]["shards"] = 2
    intop.initialize_shard_specs(collected_namespaces_env_test1, shard_manager)
    expected = [
        {"shard_id": "0", "shards": "2", "shard_name_suffix": "-0", "extra_args": ""},
        {"shard_id": "1", "shards": "2", "shard_name_suffix": "-1", "extra_args": ""},
    ]
    assert (
        expected
        == collected_namespaces_env_test1[0]["integration_specs"][0]["shard_specs"]
    )


def test_initialize_shard_specs_two_shards_explicit(
    collected_namespaces_env_test1: list[dict[str, Any]],
    shard_manager: intop.IntegrationShardManager,
):
    """
    this test shows how the explicit static sharding strategy creates two shards
    """
    collected_namespaces_env_test1[0]["integration_specs"][0][
        "shardingStrategy"
    ] = "static"
    collected_namespaces_env_test1[0]["integration_specs"][0]["shards"] = 2
    intop.initialize_shard_specs(collected_namespaces_env_test1, shard_manager)
    expected = [
        {"shard_id": "0", "shards": "2", "shard_name_suffix": "-0", "extra_args": ""},
        {"shard_id": "1", "shards": "2", "shard_name_suffix": "-1", "extra_args": ""},
    ]
    assert (
        expected
        == collected_namespaces_env_test1[0]["integration_specs"][0]["shard_specs"]
    )


def test_initialize_shard_specs_aws_account_shards(
    collected_namespaces_env_test1: list[dict[str, Any]],
    shard_manager: intop.IntegrationShardManager,
):
    """
    this test shows how the per-aws-account strategy fills the shard_specs and ignores
    aws accounts where the integration is disabled
    """
    collected_namespaces_env_test1[0]["integration_specs"][0][
        "shardingStrategy"
    ] = "per-aws-account"
    intop.initialize_shard_specs(collected_namespaces_env_test1, shard_manager)
    expected = [
        {
            "shard_name_suffix": "-acc-1",
            "shard_key": "acc-1",
            "extra_args": "--account-name acc-1",
        },
        {
            "shard_name_suffix": "-acc-2",
            "shard_key": "acc-2",
            "extra_args": "--account-name acc-2",
        },
        {
            "shard_name_suffix": "-acc-3",
            "shard_key": "acc-3",
            "extra_args": "--account-name acc-3",
        },
    ]
    assert (
        expected
        == collected_namespaces_env_test1[0]["integration_specs"][0]["shard_specs"]
    )


def test_initialize_shard_specs_extra_arg_agregation(
    collected_namespaces_env_test1: list[dict[str, Any]],
    shard_manager: intop.IntegrationShardManager,
):
    """
    this test shows how extra args are aggregated
    """
    collected_namespaces_env_test1[0]["integration_specs"][0]["extraArgs"] = "--arg"
    collected_namespaces_env_test1[0]["integration_specs"][0][
        "shardingStrategy"
    ] = "per-aws-account"
    intop.initialize_shard_specs(collected_namespaces_env_test1, shard_manager)
    expected = [
        {
            "shard_name_suffix": "-acc-1",
            "shard_key": "acc-1",
            "extra_args": "--arg --account-name acc-1",
        },
        {
            "shard_name_suffix": "-acc-2",
            "shard_key": "acc-2",
            "extra_args": "--arg --account-name acc-2",
        },
        {
            "shard_name_suffix": "-acc-3",
            "shard_key": "acc-3",
            "extra_args": "--arg --account-name acc-3",
        },
    ]
    assert (
        expected
        == collected_namespaces_env_test1[0]["integration_specs"][0]["shard_specs"]
    )


def test_initialize_shard_specs_unsupported_strategy(
    collected_namespaces_env_test1: list[dict[str, Any]],
    shard_manager: intop.IntegrationShardManager,
):
    """
    this test shows how an unsupported sharding strategy fails the integration
    """
    collected_namespaces_env_test1[0]["integration_specs"][0][
        "shardingStrategy"
    ] = "based-on-moon-cycles"
    with pytest.raises(ValueError) as e:
        intop.initialize_shard_specs(collected_namespaces_env_test1, shard_manager)
    assert e.value.args[0] == "unsupported sharding strategy 'based-on-moon-cycles'"


def test_fetch_desired_state(
    collected_namespaces_env_test1: list[dict[str, Any]],
    shard_manager: intop.IntegrationShardManager,
):
    intop.initialize_shard_specs(collected_namespaces_env_test1, shard_manager)
    ri = ResourceInventory()
    ri.initialize_resource_type("cl1", "ns1", "Deployment")
    ri.initialize_resource_type("cl1", "ns1", "Service")
    intop.fetch_desired_state(
        namespaces=collected_namespaces_env_test1,
        ri=ri,
        image_tag_from_ref=None,
    )

    resources = [
        (cluster, namespace, kind, list(data["desired"].keys()))
        for cluster, namespace, kind, data in list(ri)
    ]

    assert len(resources) == 2
    assert ("cl1", "ns1", "Deployment", ["qontract-reconcile-integ1"]) in resources
    assert ("cl1", "ns1", "Service", ["qontract-reconcile"]) in resources
