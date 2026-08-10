"""Pydantic domain models for OCM OIDC identity provider reconciliation desired state."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OcmOidcIdpAuth(BaseModel, frozen=True):
    """Auth configuration for a cluster's OIDC identity provider.

    Label interpretation stays client-side (see reconcile/rhidp_api/ocm_oidc_idp) -
    oidc_enabled/enforced are booleans computed from OCM labels by the client, not the
    raw StatusValue enum, so this service has zero knowledge of label semantics.
    """

    name: str = Field(..., description="IDP name, must match the SSO client auth name")
    issuer: str = Field(
        ..., description="Keycloak instance URL (must match the stored SSO secret)"
    )
    group_filter_regex: str | None = Field(
        default=None, description="Optional group filter regex for the SSO client"
    )
    oidc_enabled: bool = Field(
        ...,
        description="Whether an OIDC identity provider should exist for this cluster",
    )
    enforced: bool = Field(
        ...,
        description=(
            "If True, ALL foreign identity providers on this cluster are removed, "
            "not just ones matching this auth name"
        ),
    )


class OcmOidcIdpCluster(BaseModel, frozen=True):
    """A single cluster considered for RHIDP OIDC, compiled client-side from OCM labels.

    Sent for every RHIDP-managed cluster (not just oidc_enabled ones), so the current
    state (existing OCM identity providers) can still be diffed and cleaned up for
    clusters that became disabled since the last reconcile.
    """

    cluster_id: str = Field(..., description="OCM cluster id")
    name: str = Field(..., description="Cluster name")
    organization_id: str = Field(..., description="OCM organization id")
    auth: OcmOidcIdpAuth = Field(..., description="OIDC auth configuration")
