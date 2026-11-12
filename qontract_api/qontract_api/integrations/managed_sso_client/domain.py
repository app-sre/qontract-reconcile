"""Pydantic domain models for managed-sso-client."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator
from qontract_utils.keycloak_api import (
    ManagedKeycloakClient,
    ManagedKeycloakProtocolMapper,
)

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


class ProtocolMapperDesiredState(BaseModel, frozen=True, extra="forbid"):
    """A mapper configured only when its OIDC client is created."""

    name: str
    protocol_mapper: str
    config: dict[str, str] = Field(
        default_factory=dict,
        # Expose the factory default so generated clients do not send null.
        json_schema_extra={"default": {}},
        description="Defaults to an empty mapping; only declared config keys are checked for drift. "
        "Mapper configuration is applied only during client creation. "
        "Empty string values are rejected because Keycloak removes them.",
    )
    protocol: Literal["openid-connect"] = "openid-connect"

    @model_validator(mode="before")
    @classmethod
    def _discard_legacy_deleted_false(cls, value: object) -> object:
        """Accept the old client's default during rollout without restoring the field."""
        if isinstance(value, dict) and value.get("deleted") is False:
            return {key: item for key, item in value.items() if key != "deleted"}
        return value

    @field_validator("config")
    @classmethod
    def _reject_empty_config_values(cls, config: dict[str, str]) -> dict[str, str]:
        """Reject values removed by Keycloak's removeEmptyString conversion.

        Unlike client attributes, mapper config retains whitespace-only values.
        Preserve them without stripping or imposing provider-specific rules.
        """
        if "" in config.values():
            msg = "mapper config values must not be empty strings; omit unset keys"
            raise ValueError(msg)
        return config

    def to_managed_keycloak_mapper(self) -> ManagedKeycloakProtocolMapper:
        """Build a mapper for a new client's registration payload."""
        return ManagedKeycloakProtocolMapper(
            name=self.name,
            protocol=self.protocol,
            protocol_mapper=self.protocol_mapper,
            config=self.config,
        )


def _declared_mappers_match(
    declarations: list[ProtocolMapperDesiredState] | None,
    live_mappers: list[ManagedKeycloakProtocolMapper] | None,
) -> bool:
    """Compare declared identities and config keys while ignoring undeclared state.

    Unset or empty declarations leave every live mapper unmanaged. Differences
    require a new client; existing mappers are never updated or deleted.
    """
    if not declarations:
        return True
    current_mappers = {(m.protocol, m.name): m for m in live_mappers or []}
    for mapper in declarations:
        live = current_mappers.get((mapper.protocol, mapper.name))
        if live is None or live.protocol_mapper != mapper.protocol_mapper:
            return False
        if not all(
            live.config.get(key) == value for key, value in mapper.config.items()
        ):
            return False
    return True


class OidcDesiredState(BaseModel, frozen=True):
    """Desired OIDC configuration for a single managed SSO client.

    Every optional field here is "unmanaged" when None, not "empty"/"false" -
    Keycloak's client-registration PUT merges by field, so an unmanaged field
    is never sent and never diffed for drift - Keycloak's own default applies
    on create, and an existing client's value is left untouched on update.
    Only an explicitly-set value (including an explicit empty list) is
    applied and compared, except for protocol_mappers: None and [] both leave
    live mappers unmanaged. Mappers are applied only during client creation;
    declared mapper drift on an existing client requires a new client.
    `access_type` and `direct_access_grants_enabled`
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
    protocol_mappers: list[ProtocolMapperDesiredState] | None = Field(
        default=None,
        description="Client-level OIDC protocol mappers, applied only during client "
        "creation. Declared mapper drift on an existing client fails dry-runs "
        "and only logs a warning during normal execution; applying mapper "
        "changes requires a new client. Undeclared mappers and config keys are ignored; "
        "unset or an empty list leaves all mappers unmanaged. Client updates "
        "always omit protocolMappers, preserving all live mappers.",
    )
    attributes: dict[str, str] | None = Field(
        default=None,
        description="Additional Keycloak OIDC client attributes. Only keys "
        "declared here are checked for drift. Unmanaged if unset.",
    )

    @field_validator("protocol_mappers")
    @classmethod
    def _unique_protocol_mappers(
        cls, mappers: list[ProtocolMapperDesiredState] | None
    ) -> list[ProtocolMapperDesiredState] | None:
        """Reject duplicate mapper identities."""
        if mappers is not None:
            names = {(mapper.protocol, mapper.name) for mapper in mappers}
            if len(names) != len(mappers):
                msg = "protocol mapper names must be unique within each protocol"
                raise ValueError(msg)
        return mappers

    @field_validator("attributes")
    @classmethod
    def _reject_dedicated_attributes(
        cls, attributes: dict[str, str] | None
    ) -> dict[str, str] | None:
        """Reject dedicated-field overrides and blank values that cannot converge."""
        if attributes and "post.logout.redirect.uris" in attributes:
            msg = "use post_logout_redirect_uris instead of the matching attribute"
            raise ValueError(msg)
        if attributes and any(not value.strip() for value in attributes.values()):
            msg = "attribute values must not be empty or whitespace-only"
            raise ValueError(msg)
        return attributes

    def to_managed_keycloak_client(
        self, *, client_id: str, enabled: bool
    ) -> ManagedKeycloakClient:
        """Compile managed OIDC fields, including mappers for client creation."""
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
            protocol_mappers=[
                mapper.to_managed_keycloak_mapper()
                for mapper in self.protocol_mappers or []
            ]
            or None,
            extra_attributes=self.attributes or {},
        )


# Excluded when comparing desired vs. live state for drift: server-owned fields,
# plus extra_attributes since a live client's attributes map always carries
# Keycloak-managed entries (e.g. client.secret.creation.time) this schema never
# declares a desired value for - comparing them would cause permanent, spurious
# drift on every reconcile. Protocol mappers and post-logout redirect URIs
# have dedicated comparison rules.
_DRIFT_COMPARISON_EXCLUDED_FIELDS = {
    "id",
    "secret",
    "registration_access_token",
    "extra_attributes",
    "protocol_mappers",
    "post_logout_redirect_uris",
}

# Keycloak's client-registration PUT silently ignores changes to these fields
# on an existing client - the request returns 200 but the live value is
# unchanged (verified against a live instance, see APPSRE-15637). Detected
# separately from ordinary drift so the caller can fail loudly instead of
# looping forever on a PUT that never actually applies.
_IMMUTABLE_OIDC_FIELDS = frozenset({
    "default_client_scopes",
    "optional_client_scopes",
})


def _field_values_match(desired: object, current: object) -> bool:
    """Compare two field values, treating lists as order-insensitive sets.

    Keycloak returns list-valued fields (e.g. redirectUris) from a Set
    internally, so their element order is not stable across requests, and
    duplicate entries are collapsed - comparing them positionally (even
    sorted) would report spurious drift every reconcile for a duplicate in
    the desired list, and would permanently block a legitimate immutable
    scope update too.
    """
    if isinstance(desired, list) and isinstance(current, list):
        return set(desired) == set(current)
    return desired == current


class ManagedSsoClientDesiredState(BaseModel, frozen=True):
    """Desired state for a single managed SSO client."""

    client_id: str = Field(..., description="Exact Keycloak clientId, taken as-is")
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

    def matches(
        self, current: ManagedKeycloakClient, *, include_protocol_mappers: bool = True
    ) -> bool:
        """Whether a client's live Keycloak representation already matches this.

        Only compares fields this desired state actually specifies (non-None).
        Keycloak's client-registration PUT merges by field, so an unset field
        here is never sent and never managed - comparing it against whatever
        Keycloak happens to have would be permanent, spurious drift. List
        fields are compared order-insensitively (see _field_values_match).
        Only declared mappers and config keys are compared; undeclared live
        mappers are ignored. Callers checking for an update can exclude mappers,
        whose drift is reported separately by immutable_field_drift.
        """
        desired_client = self.to_managed_keycloak_client()
        desired_state = desired_client.model_dump(
            exclude=_DRIFT_COMPARISON_EXCLUDED_FIELDS, exclude_none=True
        )
        current_state = current.model_dump(exclude=_DRIFT_COMPARISON_EXCLUDED_FIELDS)
        if not all(
            _field_values_match(value, current_state.get(field))
            for field, value in desired_state.items()
        ):
            return False
        # Keycloak omits post.logout.redirect.uris when the list is empty.
        # An unset desired value remains unmanaged.
        if (
            desired_client.post_logout_redirect_uris is not None
            and not _field_values_match(
                desired_client.post_logout_redirect_uris,
                current.post_logout_redirect_uris or [],
            )
        ):
            return False
        if not all(
            current.extra_attributes.get(key) == value
            for key, value in desired_client.extra_attributes.items()
        ):
            return False
        return not include_protocol_mappers or _declared_mappers_match(
            self.oidc.protocol_mappers if self.oidc else None,
            current.protocol_mappers,
        )

    def immutable_field_drift(self, current: ManagedKeycloakClient) -> list[str]:
        """Which immutable OIDC fields differ from the client's live Keycloak state.

        Only checks fields this desired state actually specifies (non-None) -
        same unmanaged-when-unset semantic as matches(). An empty result means
        no immutable field was changed; the caller should still check matches()
        separately for ordinary (mutable) drift.
        """
        desired_state = self.to_managed_keycloak_client().model_dump(
            exclude=_DRIFT_COMPARISON_EXCLUDED_FIELDS, exclude_none=True
        )
        current_state = current.model_dump(exclude=_DRIFT_COMPARISON_EXCLUDED_FIELDS)
        drift = {
            field
            for field in _IMMUTABLE_OIDC_FIELDS
            if field in desired_state
            and not _field_values_match(desired_state[field], current_state.get(field))
        }
        if not _declared_mappers_match(
            self.oidc.protocol_mappers if self.oidc else None,
            current.protocol_mappers,
        ):
            drift.add("protocol_mappers")
        return sorted(drift)


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
