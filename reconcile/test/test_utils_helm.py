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
