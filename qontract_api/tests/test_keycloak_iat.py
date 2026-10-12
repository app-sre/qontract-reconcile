"""Unit tests for keycloak_iat.resolve_initial_access_token.

Vault secrets for a Keycloak instance's initial-access-token exist in two
coexisting shapes in production: IT's rotation-managed format
(`{"current_iat": {"id", "token"}, "previous_iat": {...}}`) and a plain
single-field secret. Both sso_client and managed_sso_client must handle
either shape transparently.
"""

import pytest

from qontract_api.keycloak_iat import resolve_initial_access_token


def test_resolves_rotation_format_regardless_of_field() -> None:
    data = {
        "current_iat": {"id": "iat-1", "token": "rotation-token"},
        "previous_iat": "",
    }

    assert (
        resolve_initial_access_token(data, None, path="keycloak/iat")
        == "rotation-token"
    )
    assert (
        resolve_initial_access_token(data, "token", path="keycloak/iat")
        == "rotation-token"
    )


def test_resolves_plain_format_via_field() -> None:
    data = {"token": "plain-token"}

    assert resolve_initial_access_token(data, "token", path="keycloak/iat") == (
        "plain-token"
    )


def test_resolves_plain_format_with_custom_field_name() -> None:
    data = {"iat": "plain-token"}

    assert resolve_initial_access_token(data, "iat", path="keycloak/iat") == (
        "plain-token"
    )


def test_missing_field_in_plain_format_raises_with_path() -> None:
    data = {"other": "value"}

    with pytest.raises(ValueError, match="keycloak/iat"):
        resolve_initial_access_token(data, "token", path="keycloak/iat")


def test_no_field_and_no_rotation_format_raises_with_path() -> None:
    data = {"other": "value"}

    with pytest.raises(ValueError, match="keycloak/iat"):
        resolve_initial_access_token(data, None, path="keycloak/iat")
