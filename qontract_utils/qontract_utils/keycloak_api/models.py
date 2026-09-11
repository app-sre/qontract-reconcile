"""Keycloak domain models.

Frozen Pydantic models scoped to only the fields actually consumed downstream (see
qontract_utils.ocm_api.models for the same convention).
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field

from qontract_utils.keycloak_api._raw_client import RawClientRepresentation


class KeycloakSsoClient(BaseModel, frozen=True):
    client_id: str
    client_secret: str
    redirect_uris: list[str]
    registration_access_token: str
    attributes: dict[str, str]


# Keycloak stores postLogoutRedirectUris as a "##"-joined string under this attribute
# key rather than as a top-level JSON array - the one OIDC field ManagedKeycloakClient
# folds into/out of the wire-level `attributes` map instead of exposing via a plain alias.
_POST_LOGOUT_REDIRECT_URIS_ATTRIBUTE_KEY = "post.logout.redirect.uris"


class ManagedKeycloakClient(BaseModel, frozen=True):
    """Typed, business-facing view of a Keycloak client.

    Scoped to the OIDC fields exposed by the managed-sso-client-oidc-1.yml schema.
    Keycloak's client-registration PUT merges by field (an omitted field is left
    unchanged, verified against a live instance), so this type only ever needs to
    carry the fields it actually manages - nothing else needs to round-trip through
    it to avoid being reset. For the same reason, every optional field here is
    `None` when unmanaged (omitted from the wire payload entirely) rather than
    defaulting to an empty list/False - an explicit `[]` is a real desired value
    (actively clears the field on Keycloak), not the same as "don't touch this".
    """

    id: str | None = None
    secret: str | None = None
    registration_access_token: str | None = None

    client_id: str
    protocol: str = "openid-connect"
    enabled: bool | None = None

    public_client: bool | None = None
    bearer_only: bool | None = None
    direct_access_grants_enabled: bool | None = None
    service_accounts_enabled: bool | None = None

    redirect_uris: list[str] = Field(default_factory=list)
    post_logout_redirect_uris: list[str] | None = None
    web_origins: list[str] | None = None

    consent_required: bool | None = None
    full_scope_allowed: bool | None = None
    default_client_scopes: list[str] | None = None
    optional_client_scopes: list[str] | None = None

    # Attributes a caller wants to set that aren't one of the named OIDC fields
    # above (e.g. rhidp sso_client's group-filter-regex). Not a "preserve on
    # update" mechanism - PUT merges by field, so this only ever carries what
    # this caller actually wants written.
    extra_attributes: dict[str, str] = Field(default_factory=dict)

    def to_raw(self) -> RawClientRepresentation:
        """Fold this typed view into Keycloak's wire-level ClientRepresentation."""
        attributes: dict[str, str] = dict(self.extra_attributes)
        if self.post_logout_redirect_uris:
            attributes[_POST_LOGOUT_REDIRECT_URIS_ATTRIBUTE_KEY] = "##".join(
                self.post_logout_redirect_uris
            )
        return RawClientRepresentation(
            id=self.id,
            secret=self.secret,
            registration_access_token=self.registration_access_token,
            client_id=self.client_id,
            protocol=self.protocol,
            enabled=self.enabled,
            public_client=self.public_client,
            bearer_only=self.bearer_only,
            direct_access_grants_enabled=self.direct_access_grants_enabled,
            service_accounts_enabled=self.service_accounts_enabled,
            redirect_uris=self.redirect_uris,
            web_origins=self.web_origins,
            consent_required=self.consent_required,
            full_scope_allowed=self.full_scope_allowed,
            default_client_scopes=self.default_client_scopes,
            optional_client_scopes=self.optional_client_scopes,
            attributes=attributes or None,
        )

    @classmethod
    def from_raw(cls, raw: RawClientRepresentation) -> Self:
        """Unfold Keycloak's wire-level ClientRepresentation into this typed view."""
        raw_attributes = dict(raw.attributes or {})
        post_logout_redirect_uris: list[str] = []
        joined = raw_attributes.pop(_POST_LOGOUT_REDIRECT_URIS_ATTRIBUTE_KEY, None)
        if joined:
            post_logout_redirect_uris = joined.split("##")
        return cls(
            id=raw.id,
            secret=raw.secret,
            registration_access_token=raw.registration_access_token,
            client_id=raw.client_id,
            protocol=raw.protocol,
            enabled=raw.enabled,
            public_client=raw.public_client,
            bearer_only=raw.bearer_only,
            direct_access_grants_enabled=raw.direct_access_grants_enabled,
            service_accounts_enabled=raw.service_accounts_enabled,
            redirect_uris=raw.redirect_uris,
            post_logout_redirect_uris=post_logout_redirect_uris,
            web_origins=raw.web_origins,
            consent_required=raw.consent_required,
            full_scope_allowed=raw.full_scope_allowed,
            default_client_scopes=raw.default_client_scopes,
            optional_client_scopes=raw.optional_client_scopes,
            extra_attributes=raw_attributes,
        )
