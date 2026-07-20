"""Keycloak domain models.

Frozen Pydantic models scoped to only the fields actually consumed downstream (see
qontract_utils.ocm_api.models for the same convention).
"""

from __future__ import annotations

from pydantic import BaseModel


class KeycloakSsoClient(BaseModel, frozen=True):
    client_id: str
    client_secret: str
    redirect_uris: list[str]
    registration_access_token: str
    attributes: dict[str, str]
