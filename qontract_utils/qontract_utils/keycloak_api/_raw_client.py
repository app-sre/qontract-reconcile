"""Wire-format models and a thin httpx2-based raw client for the Keycloak API.

Request/response bodies use pydantic `Field(alias=...)` with `serialize_by_alias=True` so
the Python side stays snake_case while the wire format matches Keycloak's camelCase
`ClientRepresentation` JSON exactly (`clientId`, `redirectUris`, ...).

RawKeycloakClient owns the URLs/paths and the JSON<->pydantic (de)serialization for each
operation. It has no business logic, no hooks, no retries - it's handed an already
authenticated/configured httpx2.Client by
qontract_utils.keycloak_api.client.KeycloakApi, which owns that client's lifecycle
(construction, close()).
"""

from __future__ import annotations

import httpx2
from pydantic import BaseModel, ConfigDict, Field


class RawClientRegistrationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    client_id: str = Field(alias="clientId")
    redirect_uris: list[str] = Field(alias="redirectUris")
    default_client_scopes: list[str] = Field(alias="defaultClientScopes")
    attributes: dict[str, str] | None = None


class RawClientRegistrationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(alias="clientId")
    secret: str
    redirect_uris: list[str] = Field(alias="redirectUris")
    registration_access_token: str = Field(alias="registrationAccessToken")
    attributes: dict[str, str] = {}


class RawKeycloakClient:
    """Thin httpx2-based Keycloak client - request building and pydantic (de)serialization only."""

    def __init__(self, client: httpx2.Client) -> None:
        self._client = client

    def register_client(
        self, data: RawClientRegistrationRequest
    ) -> RawClientRegistrationResponse:
        response = self._client.post(
            "/clients-registrations/default", json=data.model_dump(mode="json")
        )
        response.raise_for_status()
        return RawClientRegistrationResponse.model_validate(response.json())

    def delete_client(self, *, client_id: str, registration_access_token: str) -> None:
        response = self._client.delete(
            f"/clients-registrations/default/{client_id}",
            headers={"Authorization": f"Bearer {registration_access_token}"},
        )
        response.raise_for_status()
