"""Unit tests for managed_sso_client's build_keycloak_instances.

A Keycloak instance's initial-access-token secret in Vault exists in two
coexisting shapes in production: a plain single-field secret, and IT's
rotation-managed format (`{"current_iat": {"id", "token"}, ...}`). Both must
resolve to a working KeycloakApi.
"""

from unittest.mock import MagicMock, patch

from qontract_api.config import Settings
from qontract_api.integrations.managed_sso_client.domain import KeycloakInstanceRef
from qontract_api.integrations.managed_sso_client.keycloak_client_factory import (
    build_keycloak_instances,
)
from qontract_api.models import Secret

INSTANCE_URL = "https://sso.example.com/auth/realms/redhat-external"
IAT_PATH = "app-sre/keycloak/iat"


def _instance(field: str | None = "token") -> KeycloakInstanceRef:
    return KeycloakInstanceRef(
        url=INSTANCE_URL,
        initial_access_token=Secret(
            secret_manager_url="https://vault.example.com", path=IAT_PATH, field=field
        ),
    )


def test_plain_format_secret_resolves_token() -> None:
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {"token": "plain-token"}

    with patch(
        "qontract_api.integrations.managed_sso_client.keycloak_client_factory.KeycloakApi"
    ) as mock_api:
        build_keycloak_instances(
            [_instance(field="token")], MagicMock(), secret_manager, Settings()
        )

    mock_api.assert_called_once_with(
        url=INSTANCE_URL, initial_access_token="plain-token", require_https=True
    )


def test_rotation_format_secret_resolves_current_iat_token() -> None:
    secret_manager = MagicMock()
    secret_manager.read_all.return_value = {
        "current_iat": {"id": "iat-1", "token": "rotation-token"},
        "previous_iat": "",
    }

    with patch(
        "qontract_api.integrations.managed_sso_client.keycloak_client_factory.KeycloakApi"
    ) as mock_api:
        build_keycloak_instances(
            [_instance(field=None)], MagicMock(), secret_manager, Settings()
        )

    mock_api.assert_called_once_with(
        url=INSTANCE_URL, initial_access_token="rotation-token", require_https=True
    )
