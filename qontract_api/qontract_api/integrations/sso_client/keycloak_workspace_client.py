"""KeycloakWorkspaceClient: distributed-locking layer over the Keycloak API client.

Following ADR-014 (Three-Layer Architecture) - Layer 2. Register/delete are mutations,
not idempotent reads, so there is nothing to cache here - but a distributed lock per
Keycloak instance + client name/id prevents two concurrent reconcile runs from
double-registering (or double-deleting) the same SSO client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.keycloak_api import (
    KeycloakApi,
    KeycloakSsoClient,
    ManagedKeycloakClient,
)

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend

DEFAULT_CLIENT_SCOPES = ["web-origins", "acr", "profile", "roles", "email"]


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
        scopes = [*DEFAULT_CLIENT_SCOPES]
        attributes: dict[str, str] = {}
        if group_filter_regex:
            scopes.append("regex-filtered-groups")
            attributes = {"group-filter-regex": group_filter_regex}

        with self.cache.lock(self._lock_key(client_name)):
            registered = self.keycloak_api.register_client(
                ManagedKeycloakClient(
                    client_id=client_name,
                    redirect_uris=list(redirect_uris),
                    default_client_scopes=scopes,
                    extra_attributes=attributes,
                )
            )
        if registered.secret is None or registered.registration_access_token is None:
            msg = f"Keycloak did not return a secret/registration_access_token for {client_name}"
            raise ValueError(msg)
        return KeycloakSsoClient(
            client_id=registered.client_id,
            client_secret=registered.secret,
            redirect_uris=registered.redirect_uris,
            registration_access_token=registered.registration_access_token,
            attributes=registered.extra_attributes,
        )

    def delete_client(self, client_id: str, registration_access_token: str) -> None:
        """Delete a registered SSO client, locked per instance+client id."""
        with self.cache.lock(self._lock_key(client_id)):
            self.keycloak_api.delete_client(
                client_id=client_id,
                registration_access_token=registration_access_token,
            )

    def close(self) -> None:
        """Release the underlying Keycloak API client's HTTP connection."""
        self.keycloak_api.close()
