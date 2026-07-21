"""Factory for creating KeycloakWorkspaceClient instances per Keycloak realm.

Service layer should use KeycloakWorkspaceClient, not KeycloakApi directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.keycloak_api import KeycloakApi

from qontract_api.integrations.sso_client.domain import KeycloakInstanceIat
from qontract_api.integrations.sso_client.keycloak_workspace_client import (
    KeycloakWorkspaceClient,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from qontract_api.cache.base import CacheBackend
    from qontract_api.integrations.sso_client.domain import KeycloakInstanceSecret
    from qontract_api.secret_manager import SecretManager


def build_keycloak_instances(
    keycloak_secrets: Sequence[KeycloakInstanceSecret],
    cache: CacheBackend,
    secret_manager: SecretManager,
) -> dict[str, KeycloakWorkspaceClient]:
    """Build one KeycloakWorkspaceClient per Keycloak instance secret.

    Mirrors the legacy KeycloakMap construction, keyed by url since that's exactly
    what a cluster's SsoClientAuth.issuer references. The issuer URL is NOT part of
    the Vault secret data (it only contains {"current_iat": {"id", "token"}, ...}),
    so it comes from the request's KeycloakInstanceSecret.url instead.

    Args:
        keycloak_secrets: One entry per Keycloak instance (issuer URL + IAT secret ref)
        cache: Cache backend for the per-instance distributed lock
        secret_manager: Secret backend for retrieving Keycloak instance secrets

    Returns:
        Dict of Keycloak instance url -> KeycloakWorkspaceClient
    """
    instances: dict[str, KeycloakWorkspaceClient] = {}
    for entry in keycloak_secrets:
        data = secret_manager.read_all(entry.secret)
        iat = KeycloakInstanceIat(**data)
        api = KeycloakApi(url=entry.url, initial_access_token=iat.current_iat.token)
        instances[entry.url] = KeycloakWorkspaceClient(keycloak_api=api, cache=cache)
    return instances
