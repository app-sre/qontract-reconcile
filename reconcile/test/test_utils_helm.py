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
    values["integrations"][0]["extraArgs"] = "--test-extra-args"
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
    values["integrations"][0]["shards"] = 2
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("shards.yml"))
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
                "cron": "* * * * *"
            }
        ]
    }


def test_template_cron(values_cron):
    template = helm.template(values_cron)
    expected = yaml.safe_load(fxt.get("cron.yml"))
    assert template == expected
