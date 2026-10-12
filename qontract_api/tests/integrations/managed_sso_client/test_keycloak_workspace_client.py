"""Unit tests for managed_sso_client's KeycloakWorkspaceClient (caching + locking)."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.keycloak_api import ManagedKeycloakClient

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.managed_sso_client.keycloak_workspace_client import (
    KeycloakWorkspaceClient,
)

INSTANCE_URL = "https://sso.example.com/auth/realms/redhat-external"
CACHE_KEY = f"managed-sso-client:{INSTANCE_URL}:my-app-ci-bot"


@pytest.fixture
def mock_api() -> MagicMock:
    mock = MagicMock()
    mock.url = INSTANCE_URL
    return mock


@pytest.fixture
def mock_cache() -> MagicMock:
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def mock_settings() -> Settings:
    return Settings()


@pytest.fixture
def client(
    mock_api: MagicMock, mock_cache: MagicMock, mock_settings: Settings
) -> KeycloakWorkspaceClient:
    return KeycloakWorkspaceClient(
        keycloak_api=mock_api, cache=mock_cache, settings=mock_settings
    )


def _client_repr(client_id: str = "my-app-ci-bot") -> ManagedKeycloakClient:
    return ManagedKeycloakClient(
        client_id=client_id, redirect_uris=["https://example.com/callback"]
    )


# ---------------------------------------------------------------------------
# register_client
# ---------------------------------------------------------------------------


def test_register_client_is_locked_per_instance_and_client_id(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    client.register_client(_client_repr())

    mock_cache.lock.assert_called_once_with(CACHE_KEY)
    mock_api.register_client.assert_called_once()


# ---------------------------------------------------------------------------
# get_client - cache hit
# ---------------------------------------------------------------------------


def test_get_client_cache_hit_skips_api_call(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    cached = _client_repr()
    mock_cache.get_obj.return_value = cached

    result = client.get_client("my-app-ci-bot", "reg-token")

    assert result == cached
    mock_api.get_client.assert_not_called()


def test_get_client_cache_hit_skips_lock(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = _client_repr()

    client.get_client("my-app-ci-bot", "reg-token")

    mock_cache.lock.assert_not_called()


# ---------------------------------------------------------------------------
# get_client - cache miss
# ---------------------------------------------------------------------------


def test_get_client_cache_miss_calls_api_with_registration_access_token(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = None
    mock_api.get_client.return_value = _client_repr()

    client.get_client("my-app-ci-bot", "reg-token")

    mock_api.get_client.assert_called_once_with(
        client_id="my-app-ci-bot", registration_access_token="reg-token"
    )


def test_get_client_cache_miss_acquires_lock(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    mock_cache.get_obj.return_value = None
    mock_api.get_client.return_value = _client_repr()

    client.get_client("my-app-ci-bot", "reg-token")

    mock_cache.lock.assert_called_once_with(CACHE_KEY)


def test_get_client_cache_miss_stores_result_with_configured_ttl(
    client: KeycloakWorkspaceClient,
    mock_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_cache.get_obj.return_value = None
    fetched = _client_repr()
    mock_api.get_client.return_value = fetched

    client.get_client("my-app-ci-bot", "reg-token")

    mock_cache.set_obj.assert_called_once_with(
        CACHE_KEY, fetched, mock_settings.managed_sso_client.client_cache_ttl
    )


def test_get_client_double_check_inside_lock(
    client: KeycloakWorkspaceClient, mock_api: MagicMock, mock_cache: MagicMock
) -> None:
    """Second get_obj call (inside lock) returns data -> API must not be called."""
    cached = _client_repr()
    mock_cache.get_obj.side_effect = [None, cached]

    result = client.get_client("my-app-ci-bot", "reg-token")

    assert result == cached
    mock_api.get_client.assert_not_called()
    mock_cache.set_obj.assert_not_called()


# ---------------------------------------------------------------------------
# update_client - delegates + invalidates
# ---------------------------------------------------------------------------


def test_update_client_delegates_to_api(
    client: KeycloakWorkspaceClient, mock_api: MagicMock
) -> None:
    data = _client_repr()

    client.update_client("my-app-ci-bot", "reg-token", data)

    mock_api.update_client.assert_called_once_with(
        client_id="my-app-ci-bot", registration_access_token="reg-token", data=data
    )


def test_update_client_invalidates_cache(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    client.update_client("my-app-ci-bot", "reg-token", _client_repr())

    mock_cache.delete.assert_called_once_with(CACHE_KEY)


def test_update_client_is_locked_per_instance_and_client_id(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    client.update_client("my-app-ci-bot", "reg-token", _client_repr())

    mock_cache.lock.assert_called_once_with(CACHE_KEY)


# ---------------------------------------------------------------------------
# delete_client - delegates + invalidates
# ---------------------------------------------------------------------------


def test_delete_client_delegates_to_api(
    client: KeycloakWorkspaceClient, mock_api: MagicMock
) -> None:
    client.delete_client("my-app-ci-bot", "reg-token")

    mock_api.delete_client.assert_called_once_with(
        client_id="my-app-ci-bot", registration_access_token="reg-token"
    )


def test_delete_client_invalidates_cache(
    client: KeycloakWorkspaceClient, mock_cache: MagicMock
) -> None:
    client.delete_client("my-app-ci-bot", "reg-token")

    mock_cache.delete.assert_called_once_with(CACHE_KEY)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_close_closes_underlying_api(
    client: KeycloakWorkspaceClient, mock_api: MagicMock
) -> None:
    client.close()
    mock_api.close.assert_called_once()
