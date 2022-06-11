import pytest
import yaml
from reconcile.utils import helm

from .fixtures import Fixtures


fxt = Fixtures("helm")


@pytest.fixture
def values():
    return {
        "integrations": [
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
            }
        ]
    }


def test_template_basic(values):
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("basic.yml"))
    assert template == expected


def test_template_cache(values):
    values["integrations"][0]["cache"] = True
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("cache.yml"))
    assert template == expected


def test_template_command(values):
    values["integrations"][0]["command"] = "e2e-tests"
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("command.yml"))
    assert template == expected


def test_template_disable_unleash(values):
    values["integrations"][0]["disableUnleash"] = True
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("disable_unleash.yml"))
    assert template == expected


def test_template_extra_args(values):
    values["integrations"][0]["shard_specs"][0]["extra_args"] = "--test-extra-args"
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("extra_args.yml"))
    assert template == expected


def test_template_extra_env(values):
    values["integrations"][0]["extraEnv"] = [
        {
            "secretName": "secret",
            "secretKey": "key",
        },
        {
            "name": "name",
            "value": "value",
        },
    ]
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("extra_env.yml"))
    assert template == expected


def test_template_internal_certificates(values):
    values["integrations"][0]["internalCertificates"] = True
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("internal_certificates.yml"))
    assert template == expected


def test_template_logs_slack(values):
    values["integrations"][0]["logs"] = {"slack": True}
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("logs_slack.yml"))
    assert template == expected


def test_template_shards(values):
    values["integrations"][0]["shard_specs"] = [
        {
            "shard_id": "0",
            "shards": "2",
            "shard_name_suffix": "-0",
        },
        {
            "shard_id": "1",
            "shards": "2",
            "shard_name_suffix": "-1",
        },
    ]
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("shards.yml"))
    assert template == expected


def test_template_aws_account_shards(values):
    values["integrations"][0]["shard_specs"] = [
        {
            "shard_id": "0",
            "shards": "2",
            "shard_name_suffix": "-acc-1",
            "extra_args": "--account-name acc-1",
        },
        {
            "shard_id": "1",
            "shards": "2",
            "shard_name_suffix": "-acc-2",
            "extra_args": "--account-name acc-2",
        },
    ]
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("aws_account_shards.yml"))
    assert template == expected


def test_template_sleep_duration(values):
    values["integrations"][0]["sleepDurationSecs"] = 29
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("sleep_duration.yml"))
    assert template == expected


def test_template_state(values):
    values["integrations"][0]["state"] = True
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("state.yml"))
    assert template == expected


def test_template_storage(values):
    values["integrations"][0]["storage"] = "13Mi"
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("storage.yml"))
    assert template == expected


def test_template_trigger(values):
    values["integrations"][0]["trigger"] = True
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("trigger.yml"))
    assert template == expected


def test_template_exclude_service(values):
    values["excludeService"] = True
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("exclude_service.yml"))
    assert template == expected


def test_template_integrations_manager(values):
    values["integrations"][0]["name"] = "integrations-manager"
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("integrations_manager.yml"))
    assert template == expected


def test_template_environment_aware(values):
    values["integrations"][0]["environmentAware"] = True
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("environment_aware.yml"))
    assert template == expected


@pytest.fixture
def values_cron():
    return {
        "cronjobs": [
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
            }
        ]
    }


def test_template_cron(values_cron):
    template = helm.template(values_cron)
    expected = yaml.safe_load(fxt.get("cron.yml"))
    assert template == expected


def test_template_cron_dashdotdb(values_cron):
    values_cron["cronjobs"][0]["dashdotdb"] = True
    template = helm.template(values_cron)
    expected = yaml.safe_load(fxt.get("dashdotdb.yml"))
    assert template == expected


def test_template_cron_concurrency_policy(values_cron):
    values_cron["cronjobs"][0]["concurrencyPolicy"] = "Forbid"
    template = helm.template(values_cron)
    expected = yaml.safe_load(fxt.get("concurrency_policy.yml"))
    assert template == expected


def test_template_cron_restart_policy(values_cron):
    values_cron["cronjobs"][0]["restartPolicy"] = "Always"
    template = helm.template(values_cron)
    expected = yaml.safe_load(fxt.get("restart_policy.yml"))
    assert template == expected


def test_template_cron_success_history(values_cron):
    values_cron["cronjobs"][0]["successfulJobHistoryLimit"] = 42
    template = helm.template(values_cron)
    expected = yaml.safe_load(fxt.get("success_history.yml"))
    assert template == expected


def test_template_cron_failure_history(values_cron):
    values_cron["cronjobs"][0]["failedJobHistoryLimit"] = 24
    template = helm.template(values_cron)
    expected = yaml.safe_load(fxt.get("failure_history.yml"))
    assert template == expected
