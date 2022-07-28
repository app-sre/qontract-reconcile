import json
import os
import time

import httpretty
import pytest
from UnleashClient.features import Feature
from UnleashClient.strategies import Strategy

import reconcile.utils.unleash
from reconcile.utils.unleash import (
    _get_unleash_api_client,
    get_feature_toggle_default,
    get_feature_toggle_state,
    get_feature_toggles,
)


def test__get_unleash_api_client(mocker):
    a = mocker.patch("UnleashClient.UnleashClient.initialize_client")
    c = _get_unleash_api_client("https://u/api", "foo")

    assert a.call_count == 1
    assert reconcile.utils.unleash.client == c


def test__get_unleash_api_client_skip_create(mocker):
    u = mocker.patch("UnleashClient.UnleashClient")
    reconcile.utils.unleash.client = u
    a = mocker.patch("UnleashClient.UnleashClient.initialize_client")
    c = _get_unleash_api_client("https://u/api", "foo")

    assert a.call_count == 0
    assert reconcile.utils.unleash.client == c == u


def test_get_feature_toggle_default():
    assert get_feature_toggle_default(None, None)


def test_get_feature_toggle_state_env_missing():
    assert get_feature_toggle_state("foo")


def test_get_feature_toggle_state(mocker, monkeypatch):
    def enabled_func(feature, fallback_function):
        return feature == "enabled"

    os.environ["UNLEASH_API_URL"] = "foo"
    os.environ["UNLEASH_CLIENT_ACCESS_TOKEN"] = "bar"

    defaultfunc = mocker.patch(
        "reconcile.utils.unleash.get_feature_toggle_default", return_value=True
    )
    monkeypatch.setattr(
        "reconcile.utils.unleash.client",
        mocker.patch("UnleashClient.UnleashClient", autospec=True),
    )
    mocker.patch(
        "UnleashClient.UnleashClient.is_enabled",
        side_effect=enabled_func,
    )

    assert get_feature_toggle_state("enabled")
    assert get_feature_toggle_state("disabled") is False
    assert defaultfunc.call_count == 0


def test_get_feature_toggles(mocker, monkeypatch):
    c = mocker.patch("UnleashClient.UnleashClient")
    c.features = {
        "foo": Feature("foo", False, []),
        "bar": Feature("bar", True, []),
    }

    monkeypatch.setattr("reconcile.utils.unleash.client", c)
    toggles = get_feature_toggles("api", "token")

    assert toggles["foo"] == "disabled"
    assert toggles["bar"] == "enabled"


@httpretty.activate(allow_net_connect=False)
@pytest.mark.parametrize("enabled", [True, False])
def test_test_get_feature_toggle_state_with_strategy(enabled):
    os.environ["UNLEASH_API_URL"] = "http://unleash/api"
    os.environ["UNLEASH_CLIENT_ACCESS_TOKEN"] = "bar"

    features = {
        "version": 2,
        "features": [
            {
                "strategies": [
                    {
                        "name": "perCluster",
                        "constraints": [],
                        "parameters": {"cluster_name": "foo"},
                    }
                ],
                "impressionData": False,
                "enabled": enabled,
                "name": "test-strategies",
                "description": "",
                "project": "default",
                "stale": False,
                "type": "release",
                "variants": [],
            }
        ],
    }

    feature_param = (httpretty.GET, "http://unleash/api/client/features")
    httpretty.register_uri(*feature_param, body=json.dumps(features), status=200)

    register_param = (httpretty.POST, "http://unleash/api/client/register")
    httpretty.register_uri(*register_param, status=202)

    assert not get_feature_toggle_state(
        "test-strategies", context={"cluster_name": "foo"}
    )

    # Set client to None or caching will fail tests
    if enabled:
        reconcile.utils.unleash.client = None
        assert get_feature_toggle_state(
            "test-strategies", context={"cluster_name": "bar"}
        )
    else:
        reconcile.utils.unleash.client = None
        assert not get_feature_toggle_state(
            "test-strategies", context={"cluster_name": "bar"}
        )
