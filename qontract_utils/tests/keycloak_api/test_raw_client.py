"""Tests for qontract_utils.keycloak_api._raw_client's wire representation."""

from qontract_utils.keycloak_api._raw_client import RawClientRepresentation


def test_uses_camel_case_aliases_for_wire_serialization() -> None:
    data = RawClientRepresentation(
        client_id="my-client",
        redirect_uris=["https://example.com/callback"],
        root_url="https://example.com",
        standard_flow_enabled=True,
        default_client_scopes=["web-origins"],
    )

    body = data.model_dump(mode="json")

    assert body["clientId"] == "my-client"
    assert body["redirectUris"] == ["https://example.com/callback"]
    assert body["rootUrl"] == "https://example.com"
    assert body["standardFlowEnabled"] is True
    assert body["defaultClientScopes"] == ["web-origins"]


def test_populate_by_name_accepts_snake_case_construction() -> None:
    data = RawClientRepresentation(client_id="my-client")
    assert data.client_id == "my-client"


def test_defaults_leave_optional_fields_unset() -> None:
    data = RawClientRepresentation(client_id="my-client")
    assert data.redirect_uris == []
    assert data.attributes is None
    assert data.secret is None
    assert data.registration_access_token is None


def test_attributes_is_a_plain_passthrough_map() -> None:
    data = RawClientRepresentation(
        client_id="my-client", attributes={"some.custom.key": "value"}
    )
    assert data.attributes == {"some.custom.key": "value"}


def test_parses_camel_case_wire_json() -> None:
    parsed = RawClientRepresentation.model_validate(
        {
            "clientId": "my-client",
            "secret": "s3cr3t",
            "registrationAccessToken": "reg-token",
            "redirectUris": ["https://example.com/callback"],
            "attributes": {"pkce.code.challenge.method": "S256"},
        }
    )

    assert parsed.client_id == "my-client"
    assert parsed.secret == "s3cr3t"
    assert parsed.registration_access_token == "reg-token"
    assert parsed.redirect_uris == ["https://example.com/callback"]
    assert parsed.attributes == {"pkce.code.challenge.method": "S256"}
