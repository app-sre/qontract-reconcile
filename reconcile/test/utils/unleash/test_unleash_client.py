from __future__ import annotations

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any
from unittest.mock import ANY, MagicMock

import pytest

import reconcile.utils.unleash.client
from reconcile.utils.unleash.client import (
    DisableClusterStrategy,
    EnableClusterStrategy,
    _get_unleash_api_client,  # noqa: PLC2701
    get_feature_toggle_default,
    get_feature_toggle_state,
    get_feature_variant,
)

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer
    from pytest_mock import MockerFixture


@pytest.fixture(autouse=True)
def reset_client() -> Generator:
    yield
    if (c := reconcile.utils.unleash.client.client) is not None:
        c.destroy()
    reconcile.utils.unleash.client.client = None


@pytest.fixture
def mock_unleash_client(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("reconcile.utils.unleash.client.UnleashClient", autospec=True)


def _setup_unleash_httpserver(features: dict, httpserver: HTTPServer) -> HTTPServer:
    httpserver.expect_request("/client/features").respond_with_json(features)
    httpserver.expect_request("/client/register", method="post").respond_with_data(
        status=202
    )
    return httpserver


@pytest.fixture
def setup_unleash_disable_cluster_strategy(httpserver: HTTPServer) -> Callable:
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
def setup_unleash_enable_cluster_strategy(httpserver: HTTPServer) -> Callable:
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


def test__get_unleash_api_client(
    mocker: MockerFixture, mock_unleash_client: MagicMock
) -> None:
    mocked_cache_dict = mocker.patch(
        "reconcile.utils.unleash.client.CacheDict",
        autospec=True,
    )

    c = _get_unleash_api_client("https://u/api", "foo")

    mock_unleash_client.assert_called_once_with(
        url="https://u/api",
        app_name="qontract-reconcile",
        custom_headers={"Authorization": "foo"},
        cache=mocked_cache_dict.return_value,
        custom_strategies={
            "enableCluster": ANY,
            "disableCluster": ANY,
        },
    )
    call_kwargs = mock_unleash_client.call_args.kwargs
    assert isinstance(
        call_kwargs["custom_strategies"]["enableCluster"], EnableClusterStrategy
    )
    assert isinstance(
        call_kwargs["custom_strategies"]["disableCluster"], DisableClusterStrategy
    )
    mock_unleash_client.return_value.initialize_client.assert_called_once_with()
    assert reconcile.utils.unleash.client.client == c


def test__get_unleash_api_client_skip_create(mock_unleash_client: MagicMock) -> None:
    u = mock_unleash_client.return_value
    reconcile.utils.unleash.client.client = u

    c = _get_unleash_api_client("https://u/api", "foo")

    mock_unleash_client.assert_not_called()
    assert reconcile.utils.unleash.client.client == c == u


def test_get_feature_toggle_default() -> None:
    assert get_feature_toggle_default("", {})


def test_get_feature_toggle_state_env_missing() -> None:
    assert get_feature_toggle_state("foo")


def test_get_feature_toggle_state(
    mocker: MockerFixture,
    monkeypatch: pytest.MonkeyPatch,
    mock_unleash_client: MagicMock,
) -> None:
    def enabled_func(feature: str, context: Any, fallback_function: Any) -> bool:
        return feature == "enabled"

    monkeypatch.setenv("UNLEASH_API_URL", "https://u/api")
    monkeypatch.setenv("UNLEASH_CLIENT_ACCESS_TOKEN", "token")

    defaultfunc = mocker.patch(
        "reconcile.utils.unleash.client.get_feature_toggle_default", return_value=True
    )
    mock_unleash_client.return_value.is_enabled.side_effect = enabled_func

    assert get_feature_toggle_state("enabled")
    assert get_feature_toggle_state("disabled") is False
    assert defaultfunc.call_count == 0


def test_get_feature_toggle_state_with_strategy(
    setup_unleash_disable_cluster_strategy: Callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpserver = setup_unleash_disable_cluster_strategy(True)
    monkeypatch.setenv("UNLEASH_API_URL", httpserver.url_for("/"))
    monkeypatch.setenv("UNLEASH_CLIENT_ACCESS_TOKEN", "bar")
    assert not get_feature_toggle_state(
        "test-strategies", context={"cluster_name": "foo"}
    )
    assert get_feature_toggle_state("test-strategies", context={"cluster_name": "bar"})


def test_get_feature_toggle_state_disabled_with_strategy(
    setup_unleash_disable_cluster_strategy: Callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpserver = setup_unleash_disable_cluster_strategy(False)
    monkeypatch.setenv("UNLEASH_API_URL", httpserver.url_for("/"))
    monkeypatch.setenv("UNLEASH_CLIENT_ACCESS_TOKEN", "bar")
    assert not get_feature_toggle_state(
        "test-strategies", context={"cluster_name": "bar"}
    )


def test_get_feature_toggle_state_with_enable_cluster_strategy(
    setup_unleash_enable_cluster_strategy: Callable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpserver = setup_unleash_enable_cluster_strategy(True)
    monkeypatch.setenv("UNLEASH_API_URL", httpserver.url_for("/"))
    monkeypatch.setenv("UNLEASH_CLIENT_ACCESS_TOKEN", "bar")
    assert get_feature_toggle_state(
        "test-strategies", context={"cluster_name": "enabled-cluster"}
    )


def test_get_feature_variant_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNLEASH_API_URL", raising=False)
    monkeypatch.delenv("UNLEASH_CLIENT_ACCESS_TOKEN", raising=False)
    assert get_feature_variant("foo") == ""  # noqa: PLC1901


def test_get_feature_variant_env_missing_custom_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UNLEASH_API_URL", raising=False)
    monkeypatch.delenv("UNLEASH_CLIENT_ACCESS_TOKEN", raising=False)
    assert get_feature_variant("foo", default_variant="fallback") == "fallback"


@pytest.mark.parametrize(
    ("variant_response", "expected"),
    [
        pytest.param(
            {"name": "disabled", "enabled": False},
            "",
            id="disabled",
        ),
        pytest.param(
            {
                "name": "variant-a",
                "enabled": True,
                "payload": {"type": "string", "value": "my-value"},
            },
            "my-value",
            id="enabled-with-payload",
        ),
        pytest.param(
            {"name": "variant-b", "enabled": True},
            "",
            id="enabled-no-payload",
        ),
        pytest.param(
            {"name": "variant-c", "enabled": True, "payload": {}},
            "",
            id="enabled-empty-payload",
        ),
    ],
)
def test_get_feature_variant(
    monkeypatch: pytest.MonkeyPatch,
    mock_unleash_client: MagicMock,
    variant_response: dict[str, Any],
    expected: str,
) -> None:
    monkeypatch.setenv("UNLEASH_API_URL", "https://u/api")
    monkeypatch.setenv("UNLEASH_CLIENT_ACCESS_TOKEN", "token")
    mock_unleash_client.return_value.get_variant.return_value = variant_response
    assert get_feature_variant("feat") == expected


def test_get_feature_variant_with_context(
    monkeypatch: pytest.MonkeyPatch,
    mock_unleash_client: MagicMock,
) -> None:
    monkeypatch.setenv("UNLEASH_API_URL", "https://u/api")
    monkeypatch.setenv("UNLEASH_CLIENT_ACCESS_TOKEN", "token")
    mock_unleash_client.return_value.get_variant.return_value = {
        "name": "variant-a",
        "enabled": True,
        "payload": {"type": "string", "value": "ctx-value"},
    }
    result = get_feature_variant("feat", context={"userId": "123"})
    assert result == "ctx-value"
    mock_unleash_client.return_value.get_variant.assert_called_once_with(
        "feat", context={"userId": "123"}
    )
