"""Pydantic domain models for RHIDP SSO client reconciliation desired state."""

from __future__ import annotations

from urllib.parse import urlparse

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


class SsoClientSecret(BaseModel, frozen=True):
    """Vault secret schema for a registered SSO client.

    Must stay byte-compatible with reconcile/utils/keycloak.py::SSOClient - the
    not-yet-migrated ocm_oidc_idp integration reads this exact shape via
    SSOClient(**secret_reader.read_all_secret(secret)).
    """

    client_id: str
    client_name: str
    client_secret: str
    redirect_uris: list[str]
    registration_access_token: str
    registration_client_uri: str
    issuer: str
    attributes: dict[str, str] = Field(default_factory=dict)


def cluster_vault_secret_id(
    org_id: str, cluster_name: str, auth_name: str, issuer_url: str
) -> str:
    """Return the vault secret id for the given cluster.

    Format must stay exactly as-is - it's the diff key used to detect existing vs
    desired SSO clients across reconcile runs.
    """
    url = urlparse(issuer_url)
    return f"{cluster_name}-{org_id}-{auth_name}-{url.hostname}"
