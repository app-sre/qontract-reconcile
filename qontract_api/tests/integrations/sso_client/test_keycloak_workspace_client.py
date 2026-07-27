"""Unit tests for KeycloakWorkspaceClient."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.keycloak_api import KeycloakApi, KeycloakSsoClient

from qontract_api.cache.base import CacheBackend
from qontract_api.integrations.sso_client.keycloak_workspace_client import (
    KeycloakWorkspaceClient,
)


@pytest.fixture
def mock_keycloak_api() -> MagicMock:
    api = MagicMock(spec=KeycloakApi)
    api.url = "https://issuer.example.com"
    return api


@pytest.fixture
def mock_cache() -> MagicMock:
    m = MagicMock(spec=CacheBackend)
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def client(
    mock_keycloak_api: MagicMock, mock_cache: MagicMock
) -> KeycloakWorkspaceClient:
    return KeycloakWorkspaceClient(keycloak_api=mock_keycloak_api, cache=mock_cache)


def test_register_client_acquires_lock_per_client_name(
    client: KeycloakWorkspaceClient,
    mock_keycloak_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    mock_keycloak_api.register_client.return_value = KeycloakSsoClient(
        client_id="my-client",
        client_secret="secret",
        redirect_uris=["https://example.com/callback"],
        registration_access_token="rat",
        attributes={},
    )

    result = client.register_client(
        client_name="my-client", redirect_uris=["https://example.com/callback"]
    )

    assert result.client_id == "my-client"
    mock_cache.lock.assert_called_once_with(
        "keycloak:https://issuer.example.com:my-client"
    )
    mock_keycloak_api.register_client.assert_called_once_with(
        client_name="my-client",
        redirect_uris=["https://example.com/callback"],
        group_filter_regex=None,
    )


def test_delete_client_acquires_lock_per_client_id(
    client: KeycloakWorkspaceClient,
    mock_keycloak_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    client.delete_client(client_id="my-client", registration_access_token="rat")

    mock_cache.lock.assert_called_once_with(
        "keycloak:https://issuer.example.com:my-client"
    )
    mock_keycloak_api.delete_client.assert_called_once_with(
        client_id="my-client", registration_access_token="rat"
    )


def test_close_delegates_to_keycloak_api(
    client: KeycloakWorkspaceClient, mock_keycloak_api: MagicMock
) -> None:
    client.close()

    mock_keycloak_api.close.assert_called_once_with()
