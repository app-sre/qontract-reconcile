"""Pydantic domain models shared across RHIDP integrations (sso_client, ocm_oidc_idp).

Vault-secret-related models live here rather than inside a single integration folder
because the ocm_oidc_idp integration consumes the exact Vault secret schema that
sso_client writes - see SsoClientSecret's docstring for the byte-compatibility contract.
"""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field


class SsoClientSecret(BaseModel, frozen=True):
    """Vault secret schema for a registered SSO client.

    Written by sso_client, read by ocm_oidc_idp to build the desired OIDC identity
    provider config for a cluster. Must stay byte-compatible with the legacy
    reconcile/utils/keycloak.py::SSOClient shape both integrations were ported from.
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

    Format must stay exactly as-is - it's the diff key sso_client uses to detect
    existing vs desired SSO clients, and the lookup key ocm_oidc_idp uses to find the
    SSO client secret for a given cluster's OIDC identity provider config.
    """
    url = urlparse(issuer_url)
    return f"{cluster_name}-{org_id}-{auth_name}-{url.hostname}"
