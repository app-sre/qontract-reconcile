"""KeycloakWorkspaceClient: distributed-locking layer over the Keycloak API client.

Following ADR-014 (Three-Layer Architecture) - Layer 2. Register/delete are mutations,
not idempotent reads, so there is nothing to cache here - but a distributed lock per
Keycloak instance + client name/id prevents two concurrent reconcile runs from
double-registering (or double-deleting) the same SSO client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.keycloak_api import KeycloakApi, KeycloakSsoClient

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend


class KeycloakWorkspaceClient:
    """Distributed-locking layer over a single Keycloak instance's KeycloakApi."""

    def __init__(self, keycloak_api: KeycloakApi, cache: CacheBackend) -> None:
        self.keycloak_api = keycloak_api
        self.cache = cache

    def _lock_key(self, client_id: str) -> str:
        return f"keycloak:{self.keycloak_api.url}:{client_id}"

    def register_client(
        self,
        client_name: str,
        redirect_uris: list[str],
        group_filter_regex: str | None = None,
    ) -> KeycloakSsoClient:
        """Register a new SSO client, locked per instance+client name."""
        with self.cache.lock(self._lock_key(client_name)):
            return self.keycloak_api.register_client(
                client_name=client_name,
                redirect_uris=redirect_uris,
                group_filter_regex=group_filter_regex,
            )

    def delete_client(self, client_id: str, registration_access_token: str) -> None:
        """Delete a registered SSO client, locked per instance+client id."""
        with self.cache.lock(self._lock_key(client_id)):
            self.keycloak_api.delete_client(
                client_id=client_id,
                registration_access_token=registration_access_token,
            )
