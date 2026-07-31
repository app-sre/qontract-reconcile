"""Pydantic domain models for RHIDP SSO client reconciliation desired state."""

from __future__ import annotations

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class KeycloakInstanceSecret(BaseModel, frozen=True):
    """A Keycloak instance's issuer URL + the Vault location of its IAT secret.

    The Vault secret itself does not carry the issuer URL (see KeycloakInstanceIat),
    so the client must supply it explicitly alongside the secret reference.
    """

    url: str = Field(..., description="Keycloak realm base URL (issuer)")
    secret: Secret = Field(
        ..., description="Vault reference to the instance's initial-access-token secret"
    )


class KeycloakIat(BaseModel, frozen=True):
    """A single initial-access-token entry as stored in Vault."""

    id: str
    token: str


class KeycloakInstanceIat(BaseModel, frozen=True):
    """Vault secret schema for a Keycloak instance's initial-access-token.

    Only current_iat is used; previous_iat (used during token rotation) is
    intentionally not modeled/consumed yet.
    """

    current_iat: KeycloakIat


class SsoClientAuth(BaseModel, frozen=True):
    """Authentication configuration for a cluster's SSO client."""

    name: str = Field(..., description="Auth name, must match the redirect URL")
    issuer: str = Field(
        ..., description="Keycloak instance URL (routes to the matching KeycloakApi)"
    )
    group_filter_regex: str | None = Field(
        default=None, description="Optional group filter regex for the SSO client"
    )


class SsoClientCluster(BaseModel, frozen=True):
    """A single cluster considered for RHIDP, as compiled client-side from OCM labels.

    Sent for ALL rhidp-labeled clusters (not just enabled ones) so the backend can
    expose the rhidp_managed_clusters metric (all discovered clusters per org,
    regardless of status) while only reconciling rhidp_enabled ones.
    """

    name: str = Field(..., description="Cluster name")
    organization_id: str = Field(..., description="OCM organization id")
    console_url: str | None = Field(default=None, description="Cluster console URL")
    rhidp_enabled: bool = Field(
        ..., description="Whether this cluster should have an SSO client reconciled"
    )
    auth: SsoClientAuth = Field(..., description="SSO client auth configuration")
