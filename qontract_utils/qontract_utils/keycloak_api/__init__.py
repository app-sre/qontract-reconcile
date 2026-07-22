"""Keycloak API client and models.

This package provides a stateless Keycloak API client following the three-layer
architecture pattern (ADR-014), covering exactly the operations needed by
reconcile/rhidp/sso_client: registering and deleting dynamically registered SSO clients.

Layer 1 (Pure Communication):
- KeycloakApi: Stateless API client with hooks for metrics and logging
- KeycloakSsoClient: Pydantic domain model for a registered SSO client

Hook System (ADR-006):
- KeycloakApiCallContext: Context passed to hooks

Example:
    >>> from qontract_utils.keycloak_api import KeycloakApi
    >>> api = KeycloakApi(url="https://sso.example.com/auth/realms/x", initial_access_token="...")
    >>> sso_client = api.register_client(client_name="my-client", redirect_uris=["https://example.com/callback"])
    >>> api.delete_client(sso_client.client_id, sso_client.registration_access_token)
"""

from qontract_utils.keycloak_api.client import (
    TIMEOUT,
    KeycloakApi,
    KeycloakApiCallContext,
)
from qontract_utils.keycloak_api.models import KeycloakSsoClient

__all__ = [
    "TIMEOUT",
    "KeycloakApi",
    "KeycloakApiCallContext",
    "KeycloakSsoClient",
]
