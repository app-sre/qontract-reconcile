"""Unit tests for ocm_oidc_idp domain models."""

from qontract_api.integrations.ocm_oidc_idp.domain import (
    OcmOidcIdpAuth,
    OcmOidcIdpCluster,
)


def test_ocm_oidc_idp_cluster_defaults() -> None:
    cluster = OcmOidcIdpCluster(
        cluster_id="cluster-1",
        name="my-cluster",
        organization_id="org-1",
        auth=OcmOidcIdpAuth(
            name="redhat-sso",
            issuer="https://issuer.example.com",
            oidc_enabled=True,
            enforced=False,
        ),
    )
    assert cluster.cluster_id == "cluster-1"
    assert cluster.auth.group_filter_regex is None


def test_ocm_oidc_idp_auth_flags() -> None:
    auth = OcmOidcIdpAuth(
        name="redhat-sso",
        issuer="https://issuer.example.com",
        group_filter_regex="^ai-.*",
        oidc_enabled=True,
        enforced=True,
    )
    assert auth.oidc_enabled is True
    assert auth.enforced is True
    assert auth.group_filter_regex == "^ai-.*"
