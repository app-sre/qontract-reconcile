"""Wire-format models and a thin httpx2-based raw client for the Keycloak API.

RawClientRepresentation uses pydantic `Field(alias=...)` with `serialize_by_alias=True`
so the Python side stays snake_case while the wire format matches Keycloak's camelCase
`ClientRepresentation` JSON exactly (`clientId`, `redirectUris`, ...). It is a plain
mirror of that JSON shape and nothing else - no folding, no business defaults. Typed,
business-facing views built on top of it (e.g. attribute-folding for OIDC fields Keycloak
carries inside `attributes`) live in qontract_utils.keycloak_api.models instead.

RawKeycloakClient owns the URLs/paths and the JSON<->pydantic (de)serialization for each
operation. It has no business logic, no hooks, no retries - it's handed an already
authenticated/configured httpx2.Client by
qontract_utils.keycloak_api.client.KeycloakApi, which owns that client's lifecycle
(construction, close()).
"""

from __future__ import annotations

import httpx2
from pydantic import BaseModel, ConfigDict, Field


class RawClientRepresentation(BaseModel):
    """Wire-level mirror of Keycloak's `ClientRepresentation` JSON.

    Keycloak's client-registration endpoint (POST/GET/PUT
    `/clients-registrations/default`) accepts and returns this exact shape for
    register, get, and update alike, so a single type covers all three.
    """

    model_config = ConfigDict(
        populate_by_name=True, serialize_by_alias=True, frozen=True
    )

    # server-owned / response-only - never set by a caller building a request
    id: str | None = None
    secret: str | None = None
    registration_access_token: str | None = Field(
        default=None, alias="registrationAccessToken"
    )
    not_before: int | None = Field(default=None, alias="notBefore")

    client_id: str = Field(alias="clientId")
    name: str | None = None
    protocol: str = "openid-connect"
    enabled: bool | None = None
    surrogate_auth_required: bool | None = Field(
        default=None, alias="surrogateAuthRequired"
    )
    client_authenticator_type: str | None = Field(
        default=None, alias="clientAuthenticatorType"
    )
    redirect_uris: list[str] = Field(default_factory=list, alias="redirectUris")
    web_origins: list[str] | None = Field(default=None, alias="webOrigins")
    root_url: str | None = Field(default=None, alias="rootUrl")
    base_url: str | None = Field(default=None, alias="baseUrl")
    admin_url: str | None = Field(default=None, alias="adminUrl")
    public_client: bool | None = Field(default=None, alias="publicClient")
    bearer_only: bool | None = Field(default=None, alias="bearerOnly")
    consent_required: bool | None = Field(default=None, alias="consentRequired")
    standard_flow_enabled: bool | None = Field(
        default=None, alias="standardFlowEnabled"
    )
    implicit_flow_enabled: bool | None = Field(
        default=None, alias="implicitFlowEnabled"
    )
    direct_access_grants_enabled: bool | None = Field(
        default=None, alias="directAccessGrantsEnabled"
    )
    service_accounts_enabled: bool | None = Field(
        default=None, alias="serviceAccountsEnabled"
    )
    frontchannel_logout: bool | None = Field(default=None, alias="frontchannelLogout")
    full_scope_allowed: bool | None = Field(default=None, alias="fullScopeAllowed")
    always_display_in_console: bool | None = Field(
        default=None, alias="alwaysDisplayInConsole"
    )
    node_re_registration_timeout: int | None = Field(
        default=None, alias="nodeReRegistrationTimeout"
    )
    default_client_scopes: list[str] | None = Field(
        default=None, alias="defaultClientScopes"
    )
    optional_client_scopes: list[str] | None = Field(
        default=None, alias="optionalClientScopes"
    )
    default_roles: list[str] = Field(default_factory=list, alias="defaultRoles")
    authentication_flow_binding_overrides: dict[str, str] = Field(
        default_factory=dict, alias="authenticationFlowBindingOverrides"
    )

    # Keycloak's generic string-to-string map. Any typed, folded view of specific
    # keys within it belongs in qontract_utils.keycloak_api.models, not here. Kept
    # Optional (not default_factory=dict) so a request that has nothing to fold
    # omits the key entirely rather than sending an explicit empty map - Keycloak's
    # client-registration PUT merges by omitted key, not by empty-vs-absent value.
    attributes: dict[str, str] | None = None


class RawKeycloakClient:
    """Thin httpx2-based Keycloak client - request building and pydantic (de)serialization only."""

    def __init__(self, client: httpx2.Client) -> None:
        self._client = client

    def register_client(self, data: RawClientRepresentation) -> RawClientRepresentation:
        """Register a new client via Keycloak's dynamic registration endpoint.

        Authenticated with whatever bearer token is already set as the default
        Authorization header on the underlying httpx2.Client.
        """
        response = self._client.post(
            "/clients-registrations/default",
            json=data.model_dump(mode="json", exclude_none=True),
        )
        response.raise_for_status()
        return RawClientRepresentation.model_validate(response.json())

    def get_client(
        self, *, client_id: str, registration_access_token: str
    ) -> RawClientRepresentation:
        """Fetch a client's current representation.

        Does NOT rotate the registration access token - safe to call repeatedly
        with the same token.
        """
        response = self._client.get(
            f"/clients-registrations/default/{client_id}",
            headers={"Authorization": f"Bearer {registration_access_token}"},
        )
        response.raise_for_status()
        return RawClientRepresentation.model_validate(response.json())

    def update_client(
        self,
        *,
        client_id: str,
        registration_access_token: str,
        data: RawClientRepresentation,
    ) -> RawClientRepresentation:
        """Update a client's representation.

        Rotates the registration access token - the response's
        registration_access_token is a NEW token; the one passed in for auth
        becomes invalid immediately once this call succeeds.
        """
        response = self._client.put(
            f"/clients-registrations/default/{client_id}",
            json=data.model_dump(mode="json", exclude_none=True),
            headers={"Authorization": f"Bearer {registration_access_token}"},
        )
        response.raise_for_status()
        return RawClientRepresentation.model_validate(response.json())

    def delete_client(self, *, client_id: str, registration_access_token: str) -> None:
        response = self._client.delete(
            f"/clients-registrations/default/{client_id}",
            headers={"Authorization": f"Bearer {registration_access_token}"},
        )
        response.raise_for_status()
