"""Parsing for a Keycloak instance's initial-access-token (IAT) as stored in Vault.

Vault secrets for a Keycloak instance's IAT exist in two coexisting shapes in
production: IT's rotation-managed format and a plain single-field secret.
Shared by sso_client and managed_sso_client, since both register clients
against the same kinds of Keycloak instances and must tolerate either shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


class KeycloakIat(BaseModel, frozen=True):
    """A single initial-access-token entry, as stored in Vault's rotation format."""

    id: str
    token: str


class KeycloakRotatingIat(BaseModel, frozen=True):
    """IT-managed Vault secret shape for a Keycloak instance's IAT.

    Only current_iat is used; previous_iat exists for the rotation grace
    period and is intentionally not modeled/consumed.
    """

    current_iat: KeycloakIat


def resolve_initial_access_token(
    secret_data: Mapping[str, Any], field: str | None, *, path: str
) -> str:
    """Extract a Keycloak instance's IAT token from its Vault secret data.

    Detects the shape from the data itself rather than trusting `field`: a
    `current_iat` key means IT's rotation format, regardless of what `field`
    is set to; otherwise `field` names the plain-format key holding the token.

    Args:
        secret_data: all fields read from the Vault secret path
        field: which field holds the token in the plain format
        path: the Vault path secret_data was read from, for error messages only
    """
    if "current_iat" in secret_data:
        return KeycloakRotatingIat(**secret_data).current_iat.token
    if field and field in secret_data:
        return str(secret_data[field])
    msg = (
        f"{path}: could not resolve an initial-access-token from Vault data - "
        f"expected either a 'current_iat' key (rotation format) or a {field!r} "
        f"field (plain format), got keys {sorted(secret_data)}"
    )
    raise ValueError(msg)
