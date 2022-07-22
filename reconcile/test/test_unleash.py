import os
from UnleashClient.features import Feature
from UnleashClient.strategies import Strategy

import reconcile.utils.unleash
from reconcile.utils.unleash import (
    _get_unleash_api_client,
    get_feature_toggle_default,
    get_feature_toggle_state,
    get_feature_toggles,
    get_feature_toggle_strategies,
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


def test_get_feature_toggle_strategies_env_missing():
    assert get_feature_toggle_strategies("foo") is None


def test_get_feature_toggle_strategies(mocker, monkeypatch):
    os.environ["UNLEASH_API_URL"] = "foo"
    os.environ["UNLEASH_CLIENT_ACCESS_TOKEN"] = "bar"

    c = mocker.patch("UnleashClient.UnleashClient")
    c.features = {
        "foo": Feature("foo", False, [Strategy(parameters={"foo": "bar"})]),
        "bar": Feature("bar", True, []),
    }
    monkeypatch.setattr("reconcile.utils.unleash.client", c)

    strategies = get_feature_toggle_strategies("foo")
    assert strategies is not None and len(strategies) == 1
    assert strategies[0].parameters["foo"] == "bar"

    strategies = get_feature_toggle_strategies("bar")
    assert strategies is not None and len(strategies) == 0

    assert get_feature_toggle_strategies("rab") is None
