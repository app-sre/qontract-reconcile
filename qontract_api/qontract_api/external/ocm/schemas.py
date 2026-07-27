"""API schemas for OCM external integration."""

from __future__ import annotations

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class OcmClusterQueryParams(Secret):
    """Query parameters for OCM label-based cluster discovery.

    Deliberately generic - this endpoint has no notion of "rhidp" or any other
    consumer. Callers own their label_key_prefix so other OCM-label-based
    integrations can reuse it. The inherited Secret fields (secret_manager_url,
    path, field, version) resolve access_token_client_secret.
    """

    # Named ocm_url, not url, to avoid shadowing Secret.url (a property returning
    # secret_manager_url, used by SecretManager to route to the correct backend).
    ocm_url: str = Field(..., description="OCM environment base URL")
    access_token_url: str = Field(
        ..., description="OAuth2 token endpoint (client-credentials grant)"
    )
    access_token_client_id: str = Field(..., description="OAuth2 client id")
    label_key_prefix: str = Field(
        ...,
        description=(
            "Subscription/organization label key prefix to search for "
            "(e.g. 'sre-capabilities.rhidp'); matched with a trailing '%' wildcard"
        ),
    )
    org_ids: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of organization ids to restrict results to. "
            "Omit to include all matching organizations."
        ),
    )


class OcmClusterInfo(BaseModel, frozen=True):
    """A single OCM cluster matching label_key_prefix, with merged labels.

    labels is the flat, merged view of subscription-level and
    organization-level labels whose key starts with label_key_prefix
    (subscription-level labels win on key collisions). Label *interpretation*
    is left entirely to the caller.
    """

    id: str = Field(..., description="OCM cluster id")
    name: str = Field(..., description="Cluster name")
    organization_id: str = Field(..., description="OCM organization id")
    console_url: str | None = Field(default=None, description="Cluster console URL")
    external_auth_enabled: bool = Field(
        default=False, description="Whether external auth is enabled on the cluster"
    )
    labels: dict[str, str] = Field(
        default_factory=dict,
        description="Merged subscription+organization labels matching label_key_prefix",
    )


class OcmClustersResponse(BaseModel, frozen=True):
    """Response model for the cluster discovery endpoint."""

    clusters: list[OcmClusterInfo] = Field(default_factory=list)
