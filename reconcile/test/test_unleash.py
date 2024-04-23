import os
from collections.abc import Callable

import pytest
from pytest_httpserver import HTTPServer
from UnleashClient.features import Feature

import reconcile.utils.unleash
from reconcile.utils.unleash import (
    DisableClusterStrategy,
    EnableClusterStrategy,
    _get_unleash_api_client,
    _shutdown_client,
    get_feature_toggle_default,
    get_feature_toggle_state,
    get_feature_toggles,
)


@pytest.fixture
def reset_client():
    reconcile.utils.unleash.client = None


def _setup_unleash_httpserver(features: dict, httpserver: HTTPServer) -> HTTPServer:
    httpserver.expect_request("/client/features").respond_with_json(features)
    httpserver.expect_request("/client/register", method="post").respond_with_data(
        status=202
    )
    return httpserver


@pytest.fixture
def setup_unleash_disable_cluster_strategy(httpserver: HTTPServer):
    def _(enabled: bool) -> HTTPServer:
        features = {
            "version": 2,
            "features": [
                {
                    "strategies": [
                        {
                            "name": "disableCluster",
                            "constraints": [],
                            "parameters": {"cluster_name": "foo"},
                        },
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
        return _setup_unleash_httpserver(features, httpserver)

    return _


@pytest.fixture
def setup_unleash_enable_cluster_strategy(httpserver: HTTPServer):
    def _(enabled: bool) -> HTTPServer:
        features = {
            "version": 2,
            "features": [
                {
                    "strategies": [
                        {
                            "name": "enableCluster",
                            "constraints": [],
                            "parameters": {"cluster_name": "enabled-cluster"},
                        },
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

        return _setup_unleash_httpserver(features, httpserver)

    return _


def test__get_unleash_api_client(mocker):
    mocked_unleash_client = mocker.patch(
        "reconcile.utils.unleash.UnleashClient",
        autospec=True,
    )
    mocked_cache_dict = mocker.patch(
        "reconcile.utils.unleash.CacheDict",
        autospec=True,
    )

    c = _get_unleash_api_client("https://u/api", "foo")

    mocked_unleash_client.assert_called_once_with(
        url="https://u/api",
        app_name="qontract-reconcile",
        custom_headers={"Authorization": "foo"},
        cache=mocked_cache_dict.return_value,
        custom_strategies={
            "enableCluster": EnableClusterStrategy,
            "disableCluster": DisableClusterStrategy,
        },
    )
    mocked_unleash_client.return_value.initialize_client.assert_called_once_with()
    assert reconcile.utils.unleash.client == c


def test__get_unleash_api_client_skip_create(mocker):
    mocked_unleash_client = mocker.patch(
        "reconcile.utils.unleash.UnleashClient",
        autospec=True,
    )
    u = mocked_unleash_client.return_value
    reconcile.utils.unleash.client = u

    c = _get_unleash_api_client("https://u/api", "foo")

    mocked_unleash_client.assert_not_called()
    assert reconcile.utils.unleash.client == c == u


def test_get_feature_toggle_default():
    assert get_feature_toggle_default(None, None)


def test_get_feature_toggle_state_env_missing():
    assert get_feature_toggle_state("foo")


def test_get_feature_toggle_state(mocker, monkeypatch):
    def enabled_func(feature, context, fallback_function):
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


def test_get_feature_toggle_state_with_strategy(
    reset_client: None, setup_unleash_disable_cluster_strategy: Callable
):
    httpserver = setup_unleash_disable_cluster_strategy(True)
    os.environ["UNLEASH_API_URL"] = httpserver.url_for("/")
    os.environ["UNLEASH_CLIENT_ACCESS_TOKEN"] = "bar"
    assert not get_feature_toggle_state(
        "test-strategies", context={"cluster_name": "foo"}
    )
    assert get_feature_toggle_state("test-strategies", context={"cluster_name": "bar"})
    _shutdown_client()


def test_get_feature_toggle_state_disabled_with_strategy(
    reset_client: None, setup_unleash_disable_cluster_strategy: Callable
):
    httpserver = setup_unleash_disable_cluster_strategy(False)
    os.environ["UNLEASH_API_URL"] = httpserver.url_for("/")
    os.environ["UNLEASH_CLIENT_ACCESS_TOKEN"] = "bar"
    assert not get_feature_toggle_state(
        "test-strategies", context={"cluster_name": "bar"}
    )
    _shutdown_client()


def test_get_feature_toggle_state_with_enable_cluster_strategy(
    reset_client: None, setup_unleash_enable_cluster_strategy: Callable
):
    httpserver = setup_unleash_enable_cluster_strategy(True)
    os.environ["UNLEASH_API_URL"] = httpserver.url_for("/")
    os.environ["UNLEASH_CLIENT_ACCESS_TOKEN"] = "bar"
    assert get_feature_toggle_state(
        "test-strategies", context={"cluster_name": "enabled-cluster"}
    )
    _shutdown_client()
