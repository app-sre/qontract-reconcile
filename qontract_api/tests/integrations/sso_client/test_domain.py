"""Unit tests for sso_client domain models."""

from qontract_api.integrations.sso_client.domain import (
    SsoClientAuth,
    SsoClientCluster,
    SsoClientSecret,
    cluster_vault_secret_id,
)


def test_cluster_vault_secret_id_format() -> None:
    """Vault secret id format must stay exact - it's the current/desired diff key."""
    secret_id = cluster_vault_secret_id(
        org_id="org-1",
        cluster_name="my-cluster",
        auth_name="redhat-sso",
        issuer_url="https://auth.redhat.com/auth/realms/EmployeeIDP",
    )
    assert secret_id == "my-cluster-org-1-redhat-sso-auth.redhat.com"


def test_sso_client_cluster_defaults() -> None:
    cluster = SsoClientCluster(
        name="my-cluster",
        organization_id="org-1",
        console_url="https://console.example.com",
        rhidp_enabled=True,
        auth=SsoClientAuth(name="redhat-sso", issuer="https://issuer.example.com"),
    )
    assert cluster.console_url == "https://console.example.com"
    assert cluster.auth.group_filter_regex is None


def test_sso_client_secret_attributes_default_empty() -> None:
    secret = SsoClientSecret(
        client_id="c1",
        client_name="c1",
        client_secret="s1",
        redirect_uris=["https://example.com/callback"],
        registration_access_token="rat",
        registration_client_uri="https://issuer/clients-registrations/default/c1",
        issuer="https://issuer.example.com",
    )
    assert secret.attributes == {}
