from collections.abc import (
    Callable,
    Sequence,
)

import pytest
import yaml

from reconcile.gql_definitions.integrations.integrations import (
    AWSAccountShardSpecOverrideV1,
    IntegrationSpecExtraEnvV1,
    IntegrationSpecLogsV1,
)
from reconcile.integrations_manager import (
    HelmIntegrationSpec,
    ShardSpec,
    build_helm_values,
)
from reconcile.utils import helm

from .fixtures import Fixtures

fxt = Fixtures("helm")


@pytest.fixture
def helm_integration_specs(
    gql_class_factory: Callable[..., HelmIntegrationSpec]
) -> list[HelmIntegrationSpec]:
    i1 = gql_class_factory(
        HelmIntegrationSpec,
        {
            "name": "integ",
            "resources": {
                "requests": {
                    "cpu": "123",
                    "memory": "45Mi",
                },
                "limits": {
                    "cpu": "678",
                    "memory": "90Mi",
                },
            },
            "shard_specs": [
                {
                    "shard_id": "0",
                    "shards": "1",
                    "shard_name_suffix": "",
                }
            ],
        },
    )
    return [i1]


def test_template_basic(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("basic.yml"))
    assert template == expected


def test_template_cache(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].cache = True
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("cache.yml"))
    assert template == expected


def test_template_command(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].command = "app-interface-reporter"
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("command.yml"))
    assert template == expected


def test_template_disable_unleash(
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].disable_unleash = True
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("disable_unleash.yml"))
    assert template == expected


def test_template_enable_google_chat(
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].logs = IntegrationSpecLogsV1(slack=None, googleChat=True)
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("enable_google_chat.yml"))
    assert template == expected


def test_template_extra_args(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].shard_specs[0].extra_args = "--test-extra-args"
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("extra_args.yml"))
    assert template == expected


def test_template_extra_env(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].extra_env = [
        IntegrationSpecExtraEnvV1(
            name=None, value=None, secretName="secret", secretKey="key"
        ),
        IntegrationSpecExtraEnvV1(
            name="name",
            value="value",
            secretName=None,
            secretKey=None,
        ),
    ]
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("extra_env.yml"))
    assert template == expected


def test_template_internal_certificates(
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].internal_certificates = True
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("internal_certificates.yml"))
    assert template == expected


def test_template_logs_slack(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].logs = IntegrationSpecLogsV1(slack=True, googleChat=None)
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("logs_slack.yml"))
    assert template == expected


def test_template_shards(
    gql_class_factory: Callable[..., ShardSpec],
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].shard_specs = [
        gql_class_factory(
            ShardSpec,
            {
                "shard_id": "0",
                "shards": "2",
                "shard_name_suffix": "-0",
            },
        ),
        gql_class_factory(
            ShardSpec,
            {
                "shard_id": "1",
                "shards": "2",
                "shard_name_suffix": "-1",
            },
        ),
    ]
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("shards.yml"))
    assert template == expected


def test_template_aws_account_shards(
    gql_class_factory: Callable[..., ShardSpec],
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].shard_specs = [
        gql_class_factory(
            ShardSpec,
            {
                "shard_id": "0",
                "shards": "2",
                "shard_name_suffix": "-acc-1",
                "extra_args": "--account-name acc-1",
            },
        ),
        gql_class_factory(
            ShardSpec,
            {
                "shard_id": "1",
                "shards": "2",
                "shard_name_suffix": "-acc-2",
                "extra_args": "--account-name acc-2",
            },
        ),
    ]
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("aws_account_shards.yml"))
    assert template == expected


@pytest.fixture
def aws_shard_spec_override(
    gql_class_factory: Callable[..., AWSAccountShardSpecOverrideV1]
) -> AWSAccountShardSpecOverrideV1:
    return gql_class_factory(
        AWSAccountShardSpecOverrideV1,
        {
            "shard": {"name": "acc-2"},
            "imageRef": "foobar",
            "resources": {
                "requests": {"cpu": "200m", "memory": "200Mi"},
                "limits": {"cpu": "300m", "memory": "300Mi"},
            },
        },
    )


def test_template_aws_account_shard_spec_override(
    aws_shard_spec_override,
    gql_class_factory: Callable[..., ShardSpec],
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].shard_specs = [
        gql_class_factory(
            ShardSpec,
            {
                "shard_id": "0",
                "shards": "2",
                "shard_name_suffix": "-acc-1",
                "extra_args": "--account-name acc-1",
            },
        ),
        gql_class_factory(
            ShardSpec,
            {
                "shard_id": "1",
                "shards": "2",
                "shard_name_suffix": "-acc-2",
                "extra_args": "--account-name acc-2",
            },
        ),
    ]

    helm_integration_specs[0].shard_specs[
        1
    ].shard_spec_overrides = aws_shard_spec_override
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("aws_account_shard_spec_override.yml"))
    assert template == expected


def test_template_aws_account_shard_disabled(
    aws_shard_spec_override: AWSAccountShardSpecOverrideV1,
    gql_class_factory: Callable[..., ShardSpec],
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].shard_specs = [
        gql_class_factory(
            ShardSpec,
            {
                "shard_id": "0",
                "shards": "2",
                "shard_name_suffix": "-acc-1",
                "extra_args": "--account-name acc-1",
            },
        ),
        gql_class_factory(
            ShardSpec,
            {
                "shard_id": "1",
                "shards": "2",
                "shard_name_suffix": "-acc-2",
                "extra_args": "--account-name acc-2",
            },
        ),
    ]
    aws_shard_spec_override.image_ref = None
    aws_shard_spec_override.resources = None
    aws_shard_spec_override.disabled = True

    helm_integration_specs[0].shard_specs[
        1
    ].shard_spec_overrides = aws_shard_spec_override

    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("aws_account_shard_disabled.yml"))
    assert template == expected


def test_template_sleep_duration(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].sleep_duration_secs = "29"
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("sleep_duration.yml"))
    assert template == expected


def test_template_state(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].state = True
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("state.yml"))
    assert template == expected


def test_template_storage(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].storage = "13Mi"
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("storage.yml"))
    assert template == expected


def test_template_trigger(helm_integration_specs: Sequence[HelmIntegrationSpec]):
    helm_integration_specs[0].trigger = True
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("trigger.yml"))
    assert template == expected


def test_template_exclude_service(
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    values = build_helm_values(helm_integration_specs)
    values["excludeService"] = True
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("exclude_service.yml"))
    assert template == expected


def test_template_integrations_manager(
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].name = "integrations-manager"
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("integrations_manager.yml"))
    assert template == expected


def test_template_environment_aware(
    helm_integration_specs: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs[0].environment_aware = True
    template = helm.template(build_helm_values(helm_integration_specs))
    expected = yaml.safe_load(fxt.get("environment_aware.yml"))
    assert template == expected


@pytest.fixture
def helm_integration_specs_cron(
    gql_class_factory: Callable[..., HelmIntegrationSpec]
) -> list[HelmIntegrationSpec]:
    c1 = gql_class_factory(
        HelmIntegrationSpec,
        {
            "name": "integ",
            "resources": {
                "requests": {
                    "cpu": "123",
                    "memory": "45Mi",
                },
                "limits": {
                    "cpu": "678",
                    "memory": "90Mi",
                },
            },
            "cron": "* * * * *",
        },
    )
    return [c1]


def test_template_cron(
    helm_integration_specs_cron: Sequence[HelmIntegrationSpec],
):
    template = helm.template(build_helm_values(helm_integration_specs_cron))
    expected = yaml.safe_load(fxt.get("cron.yml"))
    assert template == expected


def test_template_cron_dashdotdb(
    helm_integration_specs_cron: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs_cron[0].dashdotdb = True
    template = helm.template(build_helm_values(helm_integration_specs_cron))
    expected = yaml.safe_load(fxt.get("dashdotdb.yml"))
    assert template == expected


def test_template_cron_concurrency_policy(
    helm_integration_specs_cron: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs_cron[0].concurrency_policy = "Forbid"
    template = helm.template(build_helm_values(helm_integration_specs_cron))
    expected = yaml.safe_load(fxt.get("concurrency_policy.yml"))
    assert template == expected


def test_template_cron_restart_policy(
    helm_integration_specs_cron: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs_cron[0].restart_policy = "Always"
    template = helm.template(build_helm_values(helm_integration_specs_cron))
    expected = yaml.safe_load(fxt.get("restart_policy.yml"))
    assert template == expected


def test_template_cron_success_history(
    helm_integration_specs_cron: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs_cron[0].successful_job_history_limit = 42
    template = helm.template(build_helm_values(helm_integration_specs_cron))
    expected = yaml.safe_load(fxt.get("success_history.yml"))
    assert template == expected


def test_template_cron_failure_history(
    helm_integration_specs_cron: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs_cron[0].failed_job_history_limit = 24
    template = helm.template(build_helm_values(helm_integration_specs_cron))
    expected = yaml.safe_load(fxt.get("failure_history.yml"))
    assert template == expected


def test_template_cron_enable_pushgateway(
    helm_integration_specs_cron: Sequence[HelmIntegrationSpec],
):
    helm_integration_specs_cron[0].enable_pushgateway = True
    template = helm.template(build_helm_values(helm_integration_specs_cron))
    expected = yaml.safe_load(fxt.get("enable_pushgateway.yml"))
    assert template == expected
