"""Keycloak API client and models.

This package provides a stateless Keycloak API client following the three-layer
architecture pattern (ADR-014) for registering, fetching, updating, and deleting
clients via Keycloak's dynamic client registration endpoint.

Layer 1 (Pure Communication):
- KeycloakApi: Stateless API client with hooks for metrics and logging
- KeycloakSsoClient: Pydantic domain model for a registered SSO client (narrow field set)
- ManagedKeycloakClient: Pydantic domain model for a full OIDC client representation

Hook System (ADR-006):
- KeycloakApiCallContext: Context passed to hooks

Example:
    >>> from qontract_utils.keycloak_api import KeycloakApi, ManagedKeycloakClient
    >>> api = KeycloakApi(url="https://sso.example.com/auth/realms/x", initial_access_token="...")
    >>> client = api.register_client(ManagedKeycloakClient(client_id="my-client", redirect_uris=["https://example.com/callback"]))
    >>> api.delete_client(client.client_id, client.registration_access_token)
"""

from qontract_utils.keycloak_api.client import (
    TIMEOUT,
    KeycloakApi,
    KeycloakApiCallContext,
)
from qontract_utils.keycloak_api.models import KeycloakSsoClient, ManagedKeycloakClient

__all__ = [
    "TIMEOUT",
    "KeycloakApi",
    "KeycloakApiCallContext",
    "KeycloakSsoClient",
    "ManagedKeycloakClient",
]
