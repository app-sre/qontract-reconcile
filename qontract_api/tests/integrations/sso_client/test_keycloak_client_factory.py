"""Unit tests for sso_client's build_keycloak_instances.

A Keycloak instance's initial-access-token secret in Vault exists in two
coexisting shapes in production: IT's rotation-managed format
(`{"current_iat": {"id", "token"}, ...}`) and a plain single-field secret.
Both must resolve to a working KeycloakApi.
"""

from unittest.mock import MagicMock, patch

from qontract_api.integrations.sso_client.domain import KeycloakInstanceSecret
from qontract_api.integrations.sso_client.keycloak_client_factory import (
    build_keycloak_instances,
)
from qontract_api.models import Secret

ISSUER_URL = "https://issuer.example.com"
IAT_PATH = "keycloak/instance1"


def _secret(field: str | None = None) -> KeycloakInstanceSecret:
    return KeycloakInstanceSecret(
        url=ISSUER_URL,
        secret=Secret(
            secret_manager_url="https://keycloak-vault.example.com",
            path=IAT_PATH,
            field=field,
        ),
    )


def test_rotation_format_secret_resolves_current_iat_token() -> None:
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "current_iat": {"id": "iat-1", "token": "rotation-token"},
        "previous_iat": "",
    }

    with patch(
        "qontract_api.integrations.sso_client.keycloak_client_factory.KeycloakApi"
    ) as mock_api:
        build_keycloak_instances([_secret(field=None)], MagicMock(), secret_manager)

    mock_api.assert_called_once_with(
        url=ISSUER_URL, initial_access_token="rotation-token"
    )


def test_plain_format_secret_resolves_token() -> None:
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {"token": "plain-token"}

    with patch(
        "qontract_api.integrations.sso_client.keycloak_client_factory.KeycloakApi"
    ) as mock_api:
        build_keycloak_instances([_secret(field="token")], MagicMock(), secret_manager)

    mock_api.assert_called_once_with(url=ISSUER_URL, initial_access_token="plain-token")
