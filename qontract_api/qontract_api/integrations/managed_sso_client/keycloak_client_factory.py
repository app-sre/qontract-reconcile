"""Factory for creating KeycloakWorkspaceClient instances per realm URL."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.keycloak_api import KeycloakApi

from qontract_api.integrations.managed_sso_client.keycloak_workspace_client import (
    KeycloakWorkspaceClient,
)
from qontract_api.keycloak_iat import resolve_initial_access_token

if TYPE_CHECKING:
    from collections.abc import Sequence

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.integrations.managed_sso_client.domain import (
        KeycloakInstanceRef,
    )
    from qontract_api.secret_manager import SecretManager


def build_keycloak_instances(
    instances: Sequence[KeycloakInstanceRef],
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> dict[str, KeycloakWorkspaceClient]:
    """Build one KeycloakWorkspaceClient per distinct realm URL.

    Each tenant may reference their own Keycloak instance (bring-your-own-IAT),
    so this deduplicates by realm URL rather than assuming a single shared
    instance - a client is only registered/read/deleted through the workspace
    client for the exact instance it declared. The IAT secret data itself may
    be in either of Vault's two coexisting shapes - see qontract_api.keycloak_iat.

    Args:
        instances: Keycloak instance refs referenced by the desired clients
        cache: Cache backend for the per-instance distributed lock and cache
        secret_manager: Secret backend for retrieving the instance's IAT
        settings: Settings for the per-client cache TTL

    Returns:
        Dict of realm URL -> KeycloakWorkspaceClient
    """
    clients: dict[str, KeycloakWorkspaceClient] = {}
    for instance in instances:
        if instance.url in clients:
            continue
        secret = instance.initial_access_token
        data = secret_manager.read_all(secret)
        initial_access_token = resolve_initial_access_token(
            data, secret.field, path=secret.path
        )
        api = KeycloakApi(
            url=instance.url,
            initial_access_token=initial_access_token,
            require_https=True,
        )
        clients[instance.url] = KeycloakWorkspaceClient(
            keycloak_api=api, cache=cache, settings=settings
        )
    return clients
