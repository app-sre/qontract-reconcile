"""Pydantic domain models for managed-sso-client."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, field_validator
from qontract_utils.keycloak_api import ManagedKeycloakClient

from qontract_api.models import Secret


class AccessType(StrEnum):
    """Keycloak client type."""

    CONFIDENTIAL = "confidential"
    PUBLIC = "public"
    BEARER_ONLY = "bearer-only"


class KeycloakInstanceRef(BaseModel, frozen=True):
    """A Keycloak realm a managed SSO client registers against."""

    url: str = Field(
        ..., description="Full realm base URL, e.g. https://host/auth/realms/name"
    )
    initial_access_token: Secret = Field(
        ..., description="Vault reference to this realm's initial access token (IAT)"
    )


class OidcDesiredState(BaseModel, frozen=True):
    """Desired OIDC configuration for a single managed SSO client.

    Every optional field here is "unmanaged" when None, not "empty"/"false" -
    Keycloak's client-registration PUT merges by field, so an unmanaged field
    is never sent and never diffed for drift - Keycloak's own default applies
    on create, and an existing client's value is left untouched on update.
    Only an explicitly-set value (including an explicit empty list) is
    applied and compared. `access_type` and `direct_access_grants_enabled`
    are the documented exceptions: both always resolve to a concrete value
    (see their validators below), since Keycloak's own create-time defaults
    for these two - public access type, and enabled direct access grants -
    are insecure (verified against a live instance).

    Caution for every other optional field: setting a value and later
    removing it from the desired state does NOT revert it - it only stops
    managing it, freezing Keycloak at whatever was last pushed. To actually
    undo a change, push back the field's previous explicit value (or its
    Keycloak default) rather than deleting the key.
    """

    access_type: AccessType | None = Field(
        default=None,
        validate_default=True,
        description="Keycloak client type/authentication requirement "
        "(confidential/public/bearer-only). Defaults to confidential when "
        "unset - Keycloak's own create-time default for an omitted access "
        "type is public, not confidential.",
    )

    @field_validator("access_type", mode="before")
    @classmethod
    def _default_access_type(cls, value: object) -> object:
        return value if value is not None else AccessType.CONFIDENTIAL

    direct_access_grants_enabled: bool | None = Field(
        default=None,
        validate_default=True,
        description="Enables the OAuth2 Resource Owner Password Credentials "
        "grant (client collects username/password itself, no browser "
        "redirect). Only appropriate for a trusted first-party client such "
        "as an internal CLI - never a browser-based or third-party client. "
        "Defaults to False when unset - Keycloak's own create-time default "
        "for an omitted value is True.",
    )

    @field_validator("direct_access_grants_enabled", mode="before")
    @classmethod
    def _default_direct_access_grants_enabled(cls, value: object) -> object:
        return value if value is not None else False

    service_accounts_enabled: bool | None = Field(
        default=None,
        description="Enables the OAuth2 Client Credentials grant (the "
        "client authenticates as itself for machine-to-machine calls, no "
        "end user involved). Requires access_type=confidential.",
    )

    redirect_uris: list[str] = Field(
        ...,
        description="Allowed redirect URIs for the standard login flow. "
        "Required by Keycloak - a client without at least one cannot log in.",
    )
    post_logout_redirect_uris: list[str] | None = Field(
        default=None,
        description="Allowed URIs Keycloak may redirect back to after an "
        "RP-initiated logout. Unmanaged if unset (see class docstring).",
    )
    web_origins: list[str] | None = Field(
        default=None,
        description="Allowed CORS origins for browser JavaScript calling "
        "Keycloak's endpoints directly from this client. Unmanaged if unset "
        "(see class docstring).",
    )

    consent_required: bool | None = Field(
        default=None,
        description="If true, Keycloak shows a consent screen the first "
        "time a user authorizes this client, listing requested scopes.",
    )
    full_scope_allowed: bool | None = Field(
        default=None,
        description="Whether this client is automatically granted every "
        "realm/client role, instead of only default_client_scopes/"
        "optional_client_scopes.",
    )
    default_client_scopes: list[str] | None = Field(
        default=None,
        description="Client scopes automatically included in every token "
        "issued to this client. Unmanaged if unset (see class docstring).",
    )
    optional_client_scopes: list[str] | None = Field(
        default=None,
        description="Client scopes this client may request via the scope "
        "parameter but that aren't included by default. Unmanaged if unset "
        "(see class docstring).",
    )

    def to_managed_keycloak_client(
        self, *, client_id: str, enabled: bool
    ) -> ManagedKeycloakClient:
        return ManagedKeycloakClient(
            client_id=client_id,
            enabled=enabled,
            public_client=self.access_type == AccessType.PUBLIC,
            bearer_only=self.access_type == AccessType.BEARER_ONLY,
            direct_access_grants_enabled=self.direct_access_grants_enabled,
            service_accounts_enabled=self.service_accounts_enabled,
            redirect_uris=self.redirect_uris,
            post_logout_redirect_uris=self.post_logout_redirect_uris,
            web_origins=self.web_origins,
            consent_required=self.consent_required,
            full_scope_allowed=self.full_scope_allowed,
            default_client_scopes=self.default_client_scopes,
            optional_client_scopes=self.optional_client_scopes,
        )


# Excluded when comparing desired vs. live state for drift: server-owned fields,
# plus extra_attributes since a live client's attributes map always carries
# Keycloak-managed entries (e.g. client.secret.creation.time) this schema never
# declares a desired value for - comparing them would cause permanent, spurious
# drift on every reconcile.
_DRIFT_COMPARISON_EXCLUDED_FIELDS = {
    "id",
    "secret",
    "registration_access_token",
    "extra_attributes",
}


class ManagedSsoClientDesiredState(BaseModel, frozen=True):
    """Desired state for a single managed SSO client."""

    client_id: str = Field(..., description="Exact Keycloak clientId, taken as-is")
    description: str | None = Field(
        default=None, description="Optional human-readable description of this client."
    )
    enabled: bool = Field(
        default=True,
        description="Whether this client is active on Keycloak. Set to False "
        "to deactivate it in place (Keycloak rejects logins/tokens for a "
        "disabled client) without deleting this object, which would delete "
        "the Keycloak registration and its secret entirely.",
    )
    keycloak_instance: KeycloakInstanceRef = Field(
        ..., description="The Keycloak realm to register/manage this client against."
    )
    oidc: OidcDesiredState | None = Field(
        default=None,
        description="OIDC-specific configuration. Required for a working "
        "client in this milestone - SAML is not yet supported.",
    )
    output: Secret | None = Field(
        default=None,
        description="Vault path for the tenant-facing credential secret. If "
        "None, the reconciler writes to an integration-managed default path.",
    )

    def to_managed_keycloak_client(self) -> ManagedKeycloakClient:
        """Build the representation to register/send to Keycloak."""
        if self.oidc is None:
            msg = f"{self.client_id}: no protocol-specific configuration set"
            raise ValueError(msg)
        return self.oidc.to_managed_keycloak_client(
            client_id=self.client_id, enabled=self.enabled
        )

    def matches(self, current: ManagedKeycloakClient) -> bool:
        """Whether a client's live Keycloak representation already matches this.

        Only compares fields this desired state actually specifies (non-None).
        Keycloak's client-registration PUT merges by field, so an unset field
        here is never sent and never managed - comparing it against whatever
        Keycloak happens to have would be permanent, spurious drift.
        """
        desired_state = self.to_managed_keycloak_client().model_dump(
            exclude=_DRIFT_COMPARISON_EXCLUDED_FIELDS, exclude_none=True
        )
        current_state = current.model_dump(exclude=_DRIFT_COMPARISON_EXCLUDED_FIELDS)
        return all(
            current_state.get(field) == value for field, value in desired_state.items()
        )


class ManagedSsoClientManagementSecret(BaseModel, frozen=True):
    """AppSRE-owned Vault secret. Never synced to a tenant namespace."""

    client_id: str = Field(
        ..., description="Exact Keycloak clientId this secret is for."
    )
    client_secret: str | None = Field(
        default=None,
        description="The client's Keycloak-issued secret. None for a public "
        "client - Keycloak never issues one.",
    )
    registration_access_token: str = Field(
        ...,
        description="Per-client token required for any future GET/PUT/DELETE "
        "against this client's Keycloak registration. Rotated on every PUT, "
        "so the new value must be persisted before the update is considered "
        "complete.",
    )
    issuer: str = Field(
        ..., description="Full realm base URL this client is registered against."
    )
    tenant_secret_path: str = Field(
        ..., description="Resolved Vault path of the paired tenant-facing secret"
    )

    def with_registration_access_token(self, registration_access_token: str) -> Self:
        return self.model_validate({
            **self.model_dump(),
            "registration_access_token": registration_access_token,
        })

    def with_tenant_secret_path(self, tenant_secret_path: str) -> Self:
        return self.model_validate({
            **self.model_dump(),
            "tenant_secret_path": tenant_secret_path,
        })


class ManagedSsoClientTenantSecret(BaseModel, frozen=True):
    """Tenant-facing Vault secret: credentials plus which realm they're for."""

    client_id: str = Field(
        ..., description="Exact Keycloak clientId this secret is for."
    )
    client_secret: str | None = Field(
        default=None,
        description="The client's Keycloak-issued secret. None for a public "
        "client - Keycloak never issues one.",
    )
    issuer: str = Field(
        ..., description="Full realm base URL this client is registered against."
    )
