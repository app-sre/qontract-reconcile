"""Tests for qontract_utils.keycloak_api.models."""

from qontract_utils.keycloak_api.models import KeycloakSsoClient


def test_keycloak_sso_client_fields() -> None:
    sso_client = KeycloakSsoClient(
        client_id="my-client",
        client_secret="s3cr3t",
        redirect_uris=["https://example.com/callback"],
        registration_access_token="reg-token",
        attributes={"what": "ever"},
    )
    assert sso_client.client_id == "my-client"
    assert sso_client.client_secret == "s3cr3t"
    assert sso_client.redirect_uris == ["https://example.com/callback"]
    assert sso_client.registration_access_token == "reg-token"
    assert sso_client.attributes == {"what": "ever"}
