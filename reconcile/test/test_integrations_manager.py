import copy
import os
from collections.abc import (
    Callable,
    Iterable,
)
from typing import Any

import pytest

import reconcile.integrations_manager as intop
from reconcile.gql_definitions.common.clusters_minimal import ClusterV1
from reconcile.gql_definitions.fragments.deplopy_resources import DeployResourcesFields
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.integrations.integrations import (
    AWSAccountShardSpecOverrideV1,
    EnvironmentV1,
    IntegrationSpecV1,
    IntegrationV1,
    OpenshiftClusterShardSpecOverrideV1,
    OpenshiftClusterShardSpecOverrideV1_ClusterV1,
    StaticSubShardingV1,
)
from reconcile.gql_definitions.sharding import aws_accounts as sharding_aws_accounts
from reconcile.gql_definitions.terraform_cloudflare_dns.terraform_cloudflare_zones import (
    AWSAccountV1 as AWSAccountV1_CloudFlare,
)
from reconcile.gql_definitions.terraform_cloudflare_dns.terraform_cloudflare_zones import (
    CloudflareAccountV1,
    CloudflareDnsRecordV1,
    CloudflareDnsZoneV1,
)
from reconcile.integrations_manager import HelmIntegrationSpec
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.runtime.meta import IntegrationMeta
from reconcile.utils.runtime.sharding import (
    AWSAccountShardingStrategy,
    AWSAccountShardingV1,
    CloudflareDnsZoneShardingStrategy,
    CloudflareDNSZoneShardingV1,
    IntegrationShardManager,
    OpenshiftClusterShardingStrategy,
    OpenshiftClusterShardingV1,
    ShardSpec,
    StaticShardingStrategy,
    StaticShardingV1,
)

AWS_INTEGRATION = "aws_integration"
CLOUDFLARE_INTEGRATION = "cloudflare_integration"
OPENSHIFT_INTEGRATION = "openshift_integration"


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
    environment = EnvironmentV1(name="e", parameters='{"env_param": "test"}')

    parameters = intop.collect_parameters(template, environment, "", "", None)
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
    environment = EnvironmentV1(name="env", parameters='{"env_param": "override"}')
    parameters = intop.collect_parameters(template, environment, "", "", None)
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
    environment = EnvironmentV1(name="env", parameters='{"env_param": "override"}')
    parameters = intop.collect_parameters(template, environment, "", "", None)
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
    environment = EnvironmentV1(name="env", parameters='{"IMAGE_TAG": "default"}')
    image_tag_from_ref = {"env": "f44e417"}
    mocker.patch(
        "reconcile.integrations_manager.get_image_tag_from_ref", return_value="f44e417"
    )
    parameters = intop.collect_parameters(
        template, environment, "", "", image_tag_from_ref
    )
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
def resources_2() -> dict[str, Any]:
    return {
        "requests": {
            "cpu": "200m",
            "memory": "2Mi",
        },
        "limits": {
            "cpu": "200m",
            "memory": "2Mi",
        },
    }


@pytest.fixture
def basic_integration_spec(
    gql_class_factory: Callable[..., IntegrationSpecV1], resources: dict[str, Any]
) -> IntegrationSpecV1:
    return gql_class_factory(
        IntegrationSpecV1, {"extraArgs": "integ-extra-arg", "resources": resources}
    )


@pytest.fixture
def basic_integration(
    gql_class_factory: Callable[..., IntegrationV1],
    basic_integration_spec: IntegrationSpecV1,
) -> IntegrationV1:
    return gql_class_factory(
        IntegrationV1,
        {
            "name": "basic-integration",
            "managed": [
                {
                    "namespace": {
                        "path": "path",
                        "name": "ns",
                        "cluster": {"name": "cluster"},
                        "environment": {"name": "test"},
                    },
                    "spec": basic_integration_spec.dict(
                        exclude_none=True, by_alias=True
                    ),
                    "sharding": None,
                }
            ],
        },
    )


@pytest.fixture
def helm_integration_spec(
    basic_integration_spec: IntegrationSpecV1,
) -> HelmIntegrationSpec:
    return HelmIntegrationSpec(
        **basic_integration_spec.dict(by_alias=True), name="basic-integration"
    )


def test_build_helm_values_empty():
    integrations_specs: list[HelmIntegrationSpec] = []
    expected: dict[str, list] = {
        "integrations": [],
        "cronjobs": [],
    }
    values = intop.build_helm_values(integrations_specs)
    assert values == expected


def test_build_helm_values(
    helm_integration_spec: HelmIntegrationSpec, resources: dict[str, Any]
):
    his1 = helm_integration_spec
    his2 = copy.deepcopy(his1)

    his2.name = "cron1"
    his2.cron = "yup"

    integrations_specs: list[HelmIntegrationSpec] = [his1, his2]
    expected = {
        "integrations": [
            {
                "name": "basic-integration",
                "extraArgs": "integ-extra-arg",
                "resources": resources,
                "shard_specs": [],
            },
        ],
        "cronjobs": [
            {
                "name": "cron1",
                "cron": "yup",
                "extraArgs": "integ-extra-arg",
                "resources": resources,
                "shard_specs": [],
            },
        ],
    }
    values = intop.build_helm_values(integrations_specs)
    assert values == expected


# Per-AWS-account Tests
@pytest.fixture
def aws_accounts(
    gql_class_factory: Callable[..., sharding_aws_accounts.AWSAccountV1]
) -> list[sharding_aws_accounts.AWSAccountV1]:
    a1 = gql_class_factory(sharding_aws_accounts.AWSAccountV1, {"name": "acc-1"})
    a2 = gql_class_factory(
        sharding_aws_accounts.AWSAccountV1,
        {"name": "acc-2", "disable": {"integrations": None}},
    )
    a3 = gql_class_factory(
        sharding_aws_accounts.AWSAccountV1,
        {"name": "acc-3", "disable": {"integrations": []}},
    )
    a4 = gql_class_factory(
        sharding_aws_accounts.AWSAccountV1,
        {"name": "acc-4", "disable": {"integrations": [AWS_INTEGRATION]}},
    )
    return [a1, a2, a3, a4]


@pytest.fixture
def aws_account_sharding_strategy(
    aws_accounts: list[sharding_aws_accounts.AWSAccountV1],
) -> AWSAccountShardingStrategy:
    return AWSAccountShardingStrategy(aws_accounts)


@pytest.fixture
def cloudflare_records():
    return [
        CloudflareDnsRecordV1(
            identifier="id",
            name="subdomain",
            type="CNAME",
            ttl=10,
            value="foo.com",
            priority=None,
            data=None,
            proxied=None,
        )
    ]


@pytest.fixture
def aws_account_for_cloudflare():
    return AWSAccountV1_CloudFlare(
        name="foo",
        consoleUrl="url",
        terraformUsername="bar",
        automationToken=VaultSecret(path="foo", field="bar", format=None, version=None),
        terraformState=None,
    )


@pytest.fixture
def cloudflare_account(aws_account_for_cloudflare):
    return CloudflareAccountV1(
        name="fakeaccount",
        type="free",
        description="description",
        providerVersion="0.0",
        enforceTwofactor=False,
        apiCredentials=VaultSecret(
            path="foo/bar", field="foo", format="bar", version=2
        ),
        terraformStateAccount=aws_account_for_cloudflare,
        deletionApprovals=None,
    )


@pytest.fixture
def cloudflare_dns_zones(cloudflare_account, cloudflare_records):
    return [
        CloudflareDnsZoneV1(
            identifier="zone1",
            zone="fakezone1.com",
            account=cloudflare_account,
            records=cloudflare_records,
            type="full",
            plan="free",
            delete=False,
            max_records=None,
        ),
        CloudflareDnsZoneV1(
            identifier="zone2",
            zone="fakezone2.com",
            account=cloudflare_account,
            records=cloudflare_records,
            type="full",
            plan="free",
            delete=False,
            max_records=None,
        ),
    ]


@pytest.fixture
def cloudflare_zone_sharding_strategy(
    cloudflare_dns_zones: list[CloudflareDnsZoneV1],
) -> CloudflareDnsZoneShardingStrategy:
    return CloudflareDnsZoneShardingStrategy(cloudflare_dns_zones)


@pytest.fixture
def openshift_clusters(gql_class_factory: Callable[..., ClusterV1]) -> list[ClusterV1]:
    return [
        gql_class_factory(
            ClusterV1,
            {"name": "cluster-1", "auth": [{"service": "github-org", "org": "redhat"}]},
        ),
        gql_class_factory(
            ClusterV1,
            {"name": "cluster-2", "auth": [{"service": "github-org", "org": "redhat"}]},
        ),
    ]


@pytest.fixture
def openshift_cluster_sharding_strategy(
    openshift_clusters: list[ClusterV1],
) -> OpenshiftClusterShardingStrategy:
    return OpenshiftClusterShardingStrategy(openshift_clusters)


@pytest.fixture
def shard_manager(
    aws_account_sharding_strategy: AWSAccountShardingStrategy,
    cloudflare_zone_sharding_strategy: CloudflareDnsZoneShardingStrategy,
    openshift_cluster_sharding_strategy: OpenshiftClusterShardingStrategy,
) -> IntegrationShardManager:
    return IntegrationShardManager(
        strategies={
            StaticShardingStrategy.IDENTIFIER: StaticShardingStrategy(),
            aws_account_sharding_strategy.IDENTIFIER: aws_account_sharding_strategy,
            openshift_cluster_sharding_strategy.IDENTIFIER: openshift_cluster_sharding_strategy,
            cloudflare_zone_sharding_strategy.IDENTIFIER: cloudflare_zone_sharding_strategy,
        },
        integration_runtime_meta={
            "basic-integration": IntegrationMeta(
                name="basic-integration",
                short_help="",
                args=["--arg"],
            ),
            AWS_INTEGRATION: IntegrationMeta(
                name=AWS_INTEGRATION, short_help="", args=["--account-name"]
            ),
            CLOUDFLARE_INTEGRATION: IntegrationMeta(
                name=CLOUDFLARE_INTEGRATION, short_help="", args=["--zone-name"]
            ),
            OPENSHIFT_INTEGRATION: IntegrationMeta(
                name=OPENSHIFT_INTEGRATION,
                short_help="",
                args=["--arg", "--cluster-name"],
            ),
        },
    )


def test_shard_manager_aws_account_filtering(
    aws_account_sharding_strategy: AWSAccountShardingStrategy,
):
    assert ["acc-1", "acc-2", "acc-3", "acc-4"] == [
        a.name
        for a in aws_account_sharding_strategy.filter_objects("another-integration")
    ]


def test_shard_manager_aws_account_filtering_disabled(
    aws_account_sharding_strategy: AWSAccountShardingStrategy,
):
    # acc-4 is disabled for AWS_INTEGRATION
    assert ["acc-1", "acc-2", "acc-3"] == [
        a.name for a in aws_account_sharding_strategy.filter_objects(AWS_INTEGRATION)
    ]


# Static Sharding Tests
def test_build_helm_integration_spec_no_shards(
    basic_integration: IntegrationV1,
    shard_manager: IntegrationShardManager,
):
    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )

    expected_shard_spec = ShardSpec(
        shards="1",
        shard_id="0",
        shard_spec_overrides=None,
        shard_key="",
        shard_name_suffix="",
        extra_args="integ-extra-arg",
    )

    assert len(wr) == 1
    shards = wr[0].integration_specs[0].shard_specs or []
    assert len(shards) == 1
    assert shards[0] == expected_shard_spec


def test_initialize_shard_specs_two_shards_explicit(
    basic_integration: IntegrationV1,
    shard_manager: intop.IntegrationShardManager,
):
    static_sharding = StaticShardingV1(
        strategy=StaticShardingStrategy.IDENTIFIER, shards=2
    )
    if basic_integration.managed:
        basic_integration.managed[0].sharding = static_sharding

    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )

    expected = [
        ShardSpec(
            shard_id="0",
            shards="2",
            shard_name_suffix="-0",
            extra_args="integ-extra-arg",
        ),
        ShardSpec(
            shard_id="1",
            shards="2",
            shard_name_suffix="-1",
            extra_args="integ-extra-arg",
        ),
    ]
    shards = wr[0].integration_specs[0].shard_specs or []
    assert expected == shards


# Per-AWS-Account tests
def test_initialize_shard_specs_aws_account_shards(
    basic_integration: IntegrationV1,
    shard_manager: IntegrationShardManager,
):
    """
    this test shows how the per-aws-account strategy fills the shard_specs and ignores
    aws accounts where the integration is disabled
    """
    aws_acc_sharding = AWSAccountShardingV1(
        strategy="per-aws-account", shardSpecOverrides=None
    )

    basic_integration.name = AWS_INTEGRATION
    if basic_integration.managed:
        basic_integration.managed[0].sharding = aws_acc_sharding

    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )

    expected = [
        ShardSpec(
            shard_name_suffix="-acc-1",
            shard_key="acc-1",
            extra_args="integ-extra-arg --account-name acc-1",
        ),
        ShardSpec(
            shard_name_suffix="-acc-2",
            shard_key="acc-2",
            extra_args="integ-extra-arg --account-name acc-2",
        ),
        ShardSpec(
            shard_name_suffix="-acc-3",
            shard_key="acc-3",
            extra_args="integ-extra-arg --account-name acc-3",
        ),
    ]

    shards = wr[0].integration_specs[0].shard_specs or []
    assert expected == shards


@pytest.fixture
def aws_shard_overrides(
    gql_class_factory: Callable[..., DeployResourcesFields],
    resources: dict[str, Any],
    aws_accounts: list[sharding_aws_accounts.AWSAccountV1],
) -> list[AWSAccountShardSpecOverrideV1]:
    o1 = AWSAccountShardSpecOverrideV1(
        shard=aws_accounts[0], imageRef="acc1-image", disabled=False, resources=None
    )
    resources["requests"]["cpu"] = "200m"
    resources["requests"]["memory"] = "2Mi"
    resources["limits"]["cpu"] = "300m"
    resources["limits"]["memory"] = "3Mi"

    deploy_resources = gql_class_factory(DeployResourcesFields, resources)
    o2 = AWSAccountShardSpecOverrideV1(
        shard=aws_accounts[1],
        imageRef=None,
        resources=deploy_resources,
        disabled=False,
    )
    o3 = AWSAccountShardSpecOverrideV1(
        shard=aws_accounts[2], resources=None, imageRef=None, disabled=True
    )

    return [o1, o2, o3]


def test_initialize_shard_specs_aws_account_shards_with_overrides(
    basic_integration: IntegrationV1,
    aws_shard_overrides: list[AWSAccountShardSpecOverrideV1],
    shard_manager: IntegrationShardManager,
):
    aws_acc_sharding = AWSAccountShardingV1(
        strategy=AWSAccountShardingStrategy.IDENTIFIER,
        shardSpecOverrides=aws_shard_overrides,
    )

    basic_integration.name = AWS_INTEGRATION
    if basic_integration.managed:
        basic_integration.managed[0].sharding = aws_acc_sharding

    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )

    expected = [
        ShardSpec(
            shard_name_suffix="-acc-1",
            shard_key="acc-1",
            extra_args="integ-extra-arg --account-name acc-1",
            shard_spec_overrides=aws_shard_overrides[0],
        ),
        ShardSpec(
            shard_name_suffix="-acc-2",
            shard_key="acc-2",
            extra_args="integ-extra-arg --account-name acc-2",
            shard_spec_overrides=aws_shard_overrides[1],
        ),
        ShardSpec(
            shard_name_suffix="-acc-3",
            shard_key="acc-3",
            extra_args="integ-extra-arg --account-name acc-3",
            shard_spec_overrides=aws_shard_overrides[2],
        ),
    ]

    shards = wr[0].integration_specs[0].shard_specs or []
    assert expected == shards


def test_initialize_shard_specs_aws_account_shards_extra_args_aggregation(
    basic_integration: IntegrationV1,
    shard_manager: IntegrationShardManager,
):
    """
    this test shows how the per-aws-account strategy fills the shard_specs and ignores
    aws accounts where the integration is disabled
    """
    aws_acc_sharding = AWSAccountShardingV1(
        strategy="per-aws-account", shardSpecOverrides=None
    )

    basic_integration.name = AWS_INTEGRATION
    if basic_integration.managed:
        basic_integration.managed[0].sharding = aws_acc_sharding
        basic_integration.managed[0].spec.extra_args = "--arg"

    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )

    expected = [
        ShardSpec(
            shard_name_suffix="-acc-1",
            shard_key="acc-1",
            extra_args="--arg --account-name acc-1",
        ),
        ShardSpec(
            shard_name_suffix="-acc-2",
            shard_key="acc-2",
            extra_args="--arg --account-name acc-2",
        ),
        ShardSpec(
            shard_name_suffix="-acc-3",
            shard_key="acc-3",
            extra_args="--arg --account-name acc-3",
        ),
    ]

    shards = wr[0].integration_specs[0].shard_specs or []
    assert expected == shards


# Per-Cloudflare-Zone Tests
@pytest.fixture
def cloudflarednszone_sharding() -> CloudflareDNSZoneShardingV1:
    return CloudflareDNSZoneShardingV1(
        strategy="per-cloudflare-dns-zone", shardSpecOverrides=None
    )


def test_initialize_shard_specs_cloudflare_zone_shards(
    basic_integration: IntegrationV1,
    cloudflarednszone_sharding: CloudflareDNSZoneShardingV1,
    shard_manager: intop.IntegrationShardManager,
):
    """
    The per-cloudflare-zone strategy would result in two shards when there is two zones.
    """
    if basic_integration.managed:
        basic_integration.name = CLOUDFLARE_INTEGRATION
        basic_integration.managed[0].sharding = cloudflarednszone_sharding

    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )

    expected = [
        ShardSpec(
            shard_key="fakeaccount-zone1",
            shard_name_suffix="-fakeaccount-zone1",
            extra_args="integ-extra-arg --zone-name zone1",
        ),
        ShardSpec(
            shard_key="fakeaccount-zone2",
            shard_name_suffix="-fakeaccount-zone2",
            extra_args="integ-extra-arg --zone-name zone2",
        ),
    ]

    shards = wr[0].integration_specs[0].shard_specs or []
    assert shards == expected


def test_initialize_shard_specs_cloudflare_zone_shards_raise_exception(
    basic_integration: IntegrationV1,
    cloudflarednszone_sharding: CloudflareDNSZoneShardingV1,
    shard_manager: intop.IntegrationShardManager,
):
    """
    The per-cloudflare-zone strategy will raise an exception when --zone-name is not set.
    """
    if basic_integration.managed:
        basic_integration.managed[0].sharding = cloudflarednszone_sharding

    with pytest.raises(ValueError) as e:
        intop.collect_integrations_environment(
            [basic_integration], "test", shard_manager
        )

    assert (
        e.value.args[0]
        == f"integration basic-integration does not support the provided argument. --zone-name is required by the '{CloudflareDnsZoneShardingStrategy.IDENTIFIER}' sharding strategy."
    )


# Per-Openshift-Clusters tests
@pytest.fixture
def openshift_clusters_sharding() -> OpenshiftClusterShardingV1:
    return OpenshiftClusterShardingV1(
        strategy=OpenshiftClusterShardingStrategy.IDENTIFIER, shardSpecOverrides=None
    )


@pytest.fixture
def openshift_clusters_shard_spec_override(
    openshift_clusters: list[ClusterV1], resources_2: dict[str, Any]
) -> OpenshiftClusterShardSpecOverrideV1:
    return OpenshiftClusterShardSpecOverrideV1(
        shard=OpenshiftClusterShardSpecOverrideV1_ClusterV1(
            name=openshift_clusters[0].name
        ),
        imageRef=None,
        disabled=False,
        resources=resources_2,
        subSharding=None,
    )


def test_initialize_shard_specs_openshift_clusters(
    basic_integration: IntegrationV1,
    openshift_clusters_sharding: OpenshiftClusterShardingV1,
    shard_manager: IntegrationShardManager,
):
    if basic_integration.managed:
        basic_integration.name = OPENSHIFT_INTEGRATION
        basic_integration.managed[0].sharding = openshift_clusters_sharding

    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )
    expected = [
        ShardSpec(
            shards="",
            shard_id="",
            shard_spec_overrides=None,
            shard_key="cluster-1",
            shard_name_suffix="-cluster-1",
            extra_args="integ-extra-arg --cluster-name cluster-1",
        ),
        ShardSpec(
            shards="",
            shard_id="",
            shard_spec_overrides=None,
            shard_key="cluster-2",
            shard_name_suffix="-cluster-2",
            extra_args="integ-extra-arg --cluster-name cluster-2",
        ),
    ]
    shards = wr[0].integration_specs[0].shard_specs or []
    assert shards == expected


def test_initialize_shard_specs_openshift_clusters_subsharding_w_overrides(
    basic_integration: IntegrationV1,
    openshift_clusters_sharding: OpenshiftClusterShardingV1,
    openshift_clusters_shard_spec_override: OpenshiftClusterShardSpecOverrideV1,
    shard_manager: IntegrationShardManager,
    resources_2: dict[str, Any],
):
    openshift_clusters_shard_spec_override.sub_sharding = StaticSubShardingV1(
        strategy=StaticShardingStrategy.IDENTIFIER, shards=2
    )

    openshift_clusters_shard_spec_override.image_ref = "my-test-image"

    if basic_integration.managed:
        basic_integration.name = OPENSHIFT_INTEGRATION
        basic_integration.managed[0].sharding = openshift_clusters_sharding
        basic_integration.managed[0].sharding.shard_spec_overrides = [
            openshift_clusters_shard_spec_override
        ]

    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )
    expected = [
        ShardSpec(
            shards="2",
            shard_id="0",
            shard_spec_overrides=OpenshiftClusterShardSpecOverrideV1(
                shard=OpenshiftClusterShardSpecOverrideV1_ClusterV1(name="cluster-1"),
                imageRef="my-test-image",
                disabled=False,
                resources=resources_2,
                subSharding=None,
            ),
            shard_key="cluster-1",
            shard_name_suffix="-cluster-1-0",
            extra_args="integ-extra-arg --cluster-name cluster-1",
        ),
        ShardSpec(
            shards="2",
            shard_id="1",
            shard_spec_overrides=OpenshiftClusterShardSpecOverrideV1(
                shard=OpenshiftClusterShardSpecOverrideV1_ClusterV1(name="cluster-1"),
                imageRef="my-test-image",
                disabled=False,
                resources=resources_2,
                subSharding=None,
            ),
            shard_key="cluster-1",
            shard_name_suffix="-cluster-1-1",
            extra_args="integ-extra-arg --cluster-name cluster-1",
        ),
        ShardSpec(
            shards="",
            shard_id="",
            shard_spec_overrides=None,
            shard_key="cluster-2",
            shard_name_suffix="-cluster-2",
            extra_args="integ-extra-arg --cluster-name cluster-2",
        ),
    ]
    shards = wr[0].integration_specs[0].shard_specs or []
    assert shards == expected


def test_initialize_shard_specs_openshift_clusters_disabled_shard(
    basic_integration: IntegrationV1,
    openshift_clusters_sharding: OpenshiftClusterShardingV1,
    openshift_clusters_shard_spec_override: OpenshiftClusterShardSpecOverrideV1,
    shard_manager: IntegrationShardManager,
    resources_2: dict[str, Any],
):
    openshift_clusters_shard_spec_override.disabled = True

    if basic_integration.managed:
        basic_integration.name = OPENSHIFT_INTEGRATION
        basic_integration.managed[0].sharding = openshift_clusters_sharding
        basic_integration.managed[0].sharding.shard_spec_overrides = [
            openshift_clusters_shard_spec_override
        ]

    wr = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )
    expected = [
        ShardSpec(
            shards="",
            shard_id="",
            shard_spec_overrides=OpenshiftClusterShardSpecOverrideV1(
                shard=OpenshiftClusterShardSpecOverrideV1_ClusterV1(name="cluster-1"),
                imageRef=None,
                disabled=True,
                resources=resources_2,
                subSharding=None,
            ),
            shard_key="cluster-1",
            shard_name_suffix="-cluster-1",
            extra_args="integ-extra-arg --cluster-name cluster-1",
        ),
        ShardSpec(
            shards="",
            shard_id="",
            shard_spec_overrides=None,
            shard_key="cluster-2",
            shard_name_suffix="-cluster-2",
            extra_args="integ-extra-arg --cluster-name cluster-2",
        ),
    ]
    shards = wr[0].integration_specs[0].shard_specs or []
    assert shards == expected


def test_fetch_desired_state(
    basic_integration: IntegrationV1,
    shard_manager: intop.IntegrationShardManager,
):
    integrations_environments = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )
    # intop.initialize_shard_specs(collected_namespaces_env_test1, shard_manager)
    ri = ResourceInventory()
    ri.initialize_resource_type("cluster", "ns", "Deployment")
    ri.initialize_resource_type("cluster", "ns", "Service")
    intop.fetch_desired_state(
        integrations_environments=integrations_environments,
        ri=ri,
        upstream="http://localhost",
        image="image",
        image_tag_from_ref=None,
    )

    resources = [
        (cluster, namespace, kind, list(data["desired"].keys()))
        for cluster, namespace, kind, data in list(ri)
    ]

    assert len(resources) == 2
    assert (
        "cluster",
        "ns",
        "Deployment",
        ["qontract-reconcile-basic-integration"],
    ) in resources
    assert ("cluster", "ns", "Service", ["qontract-reconcile"]) in resources


def test_fetch_desired_state_upstream(
    basic_integration: IntegrationV1,
    shard_manager: intop.IntegrationShardManager,
):
    upstream = "a"
    basic_integration.upstream = upstream

    integrations_environments = intop.collect_integrations_environment(
        [basic_integration], "test", shard_manager
    )

    ri = ResourceInventory()
    ri.initialize_resource_type("cluster", "ns", "Deployment")
    ri.initialize_resource_type("cluster", "ns", "Service")

    intop.fetch_desired_state(
        integrations_environments=integrations_environments,
        ri=ri,
        upstream=upstream,
        image="image",
        image_tag_from_ref=None,
    )

    resources = [
        (cluster, namespace, kind, list(data["desired"].keys()), data["desired"])
        for cluster, namespace, kind, data in list(ri)
    ]

    assert len(resources) == 2
    assert [
        x[4]["qontract-reconcile-basic-integration"].caller
        for x in resources
        if x[3] == ["qontract-reconcile-basic-integration"]
    ] == [upstream]


@pytest.fixture
def integrations(basic_integration: IntegrationV1) -> list[IntegrationV1]:
    i1 = basic_integration
    i2 = copy.deepcopy(i1)
    i3 = copy.deepcopy(i1)
    i4 = copy.deepcopy(i1)
    if i2.managed:
        i2.managed[0].namespace.environment.name = "test2"
    if i3.managed:
        i3.managed[0].namespace.environment.name = "test2"
    if i4.managed:
        i4.managed[0].namespace.environment.name = "test3"
    return [i1, i2, i3, i4]


def test_collect_ingegrations_environment(
    integrations: list[IntegrationV1], shard_manager: IntegrationShardManager
):
    ie = intop.collect_integrations_environment(integrations, "test2", shard_manager)
    assert len(ie[0].integration_specs) == 2
    assert ie[0].namespace.environment.name == "test2"


def test_collect_ingegrations_environment_no_env(
    integrations: list[IntegrationV1], shard_manager: IntegrationShardManager
):
    ie = intop.collect_integrations_environment(integrations, "", shard_manager)
    assert len(ie[0].integration_specs) == 4


def test_filter_with_upstream(integrations: list[IntegrationV1]):
    upstream = "an-upstream"
    if integrations:
        integrations[0].name = "integ-with-upstream"
        integrations[0].upstream = upstream

    filtered_integrations = intop.filter_integrations(integrations, upstream)

    assert isinstance(filtered_integrations, list)
    assert len(filtered_integrations) == 1
    assert filtered_integrations[0].name == "integ-with-upstream"


def test_filter_with_upstream_none(integrations: Iterable[IntegrationV1]):
    filtered_integrations = intop.filter_integrations(integrations, None)

    assert filtered_integrations == integrations
