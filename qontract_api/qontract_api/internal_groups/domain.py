"""Shared Internal Groups domain models."""

from __future__ import annotations

from pydantic import Field

from qontract_api.models import Secret


class InternalGroupsConnectionSecret(Secret):
    """Vault reference for Internal Groups API OAuth credentials.

    ``read_all`` must return api_url, issuer_url, client_id, and client_secret.
    """

    api_url: str = Field(..., description="Internal Groups API base URL")
    issuer_url: str = Field(
        ..., description="OIDC issuer URL for client-credentials token"
    )
    client_id: str = Field(..., description="OAuth client id")
