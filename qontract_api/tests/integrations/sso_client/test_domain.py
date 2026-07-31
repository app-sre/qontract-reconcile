"""Unit tests for sso_client domain models."""

from qontract_api.integrations.sso_client.domain import SsoClientAuth, SsoClientCluster


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
