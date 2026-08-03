"""Shared OCM domain models, used by every OCM-backed integration."""

from __future__ import annotations

from pydantic import Field

from qontract_api.models import Secret


class OcmConnectionParams(Secret):
    """OCM environment connection details, shared by every OCM-backed integration.

    Deliberately generic - carries no notion of "rhidp" or any other consumer. The
    inherited Secret fields (secret_manager_url, path, field, version) resolve
    access_token_client_secret.
    """

    # Named ocm_url, not url, to avoid shadowing Secret.url (a property returning
    # secret_manager_url, used by SecretManager to route to the correct backend).
    ocm_url: str = Field(..., description="OCM environment base URL")
    access_token_url: str = Field(
        ..., description="OAuth2 token endpoint (client-credentials grant)"
    )
    access_token_client_id: str = Field(..., description="OAuth2 client id")
