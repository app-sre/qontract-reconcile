"""KeycloakWorkspaceClient: caching + distributed-locking layer over the Keycloak API client.

Register/update/delete are mutations; get_client is the only cacheable read
here, with a TTL (settings.managed_sso_client.client_cache_ttl) since Keycloak
has no change-notification mechanism to invalidate it proactively otherwise.
update_client/delete_client invalidate the cache entry they made stale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.keycloak_api import KeycloakApi, ManagedKeycloakClient

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings


class KeycloakWorkspaceClient:
    """Caching + distributed-locking layer over a single Keycloak realm's KeycloakApi."""

    def __init__(
        self, keycloak_api: KeycloakApi, cache: CacheBackend, settings: Settings
    ) -> None:
        self.keycloak_api = keycloak_api
        self.cache = cache
        self.settings = settings

    def _client_key(self, client_id: str) -> str:
        """Shared key for both the per-client distributed lock and its cache entry."""
        return f"managed-sso-client:{self.keycloak_api.url}:{client_id}"

    def register_client(self, data: ManagedKeycloakClient) -> ManagedKeycloakClient:
        """Register a new managed SSO client, locked per instance+client id."""
        with self.cache.lock(self._client_key(data.client_id)):
            return self.keycloak_api.register_client(data)

    def get_client(
        self, client_id: str, registration_access_token: str
    ) -> ManagedKeycloakClient:
        """Fetch a managed SSO client's live representation, cached per instance+client id."""
        cache_key = self._client_key(client_id)
        cached = self.cache.get_obj(cache_key, ManagedKeycloakClient)
        if cached:
            return cached

        with self.cache.lock(cache_key):
            cached = self.cache.get_obj(cache_key, ManagedKeycloakClient)
            if cached:
                return cached

            client = self.keycloak_api.get_client(
                client_id=client_id,
                registration_access_token=registration_access_token,
            )
            self.cache.set_obj(
                cache_key, client, self.settings.managed_sso_client.client_cache_ttl
            )
            return client

    def update_client(
        self,
        client_id: str,
        registration_access_token: str,
        data: ManagedKeycloakClient,
    ) -> ManagedKeycloakClient:
        """Update a managed SSO client in place, locked per instance+client id.

        Invalidates the cached representation - the caller must not treat the
        rotated registration_access_token as cacheable state either way.
        """
        cache_key = self._client_key(client_id)
        with self.cache.lock(cache_key):
            updated = self.keycloak_api.update_client(
                client_id=client_id,
                registration_access_token=registration_access_token,
                data=data,
            )
            self.cache.delete(cache_key)
            return updated

    def delete_client(self, client_id: str, registration_access_token: str) -> None:
        """Delete a registered managed SSO client, locked per instance+client id."""
        cache_key = self._client_key(client_id)
        with self.cache.lock(cache_key):
            self.keycloak_api.delete_client(
                client_id=client_id,
                registration_access_token=registration_access_token,
            )
            self.cache.delete(cache_key)

    def close(self) -> None:
        """Release the underlying Keycloak API client's HTTP connection."""
        self.keycloak_api.close()
