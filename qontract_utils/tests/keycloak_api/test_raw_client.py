"""Tests for qontract_utils.keycloak_api._raw_client."""

import json

import httpx2
import pytest
from qontract_utils.keycloak_api._raw_client import (
    RawClientRepresentation,
    RawKeycloakClient,
)


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
    assert data.default_roles is None
    assert data.authentication_flow_binding_overrides is None


def test_unmanaged_default_roles_and_flow_overrides_omitted_from_wire_payload() -> None:
    """A field this client never sets must never appear in an update/register body.

    exclude_none=True only drops None - a concrete default_factory=list/dict
    value would still serialize as an explicit empty value, wiping whatever
    Keycloak already has for a field we never intended to manage.
    """
    data = RawClientRepresentation(client_id="my-client")

    body = data.model_dump(mode="json", exclude_none=True)

    assert "defaultRoles" not in body
    assert "authenticationFlowBindingOverrides" not in body


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


@pytest.mark.parametrize("method", ["POST", "GET", "PUT", "DELETE"])
@pytest.mark.parametrize(
    ("status_code", "body", "expected_details"),
    [
        (
            403,
            (
                '{"error":"insufficient_scope","error_description":'
                "\"Policy 'Allowed Protocol Mapper Types' rejected request to "
                'client-registration service. Details: ProtocolMapper type not allowed"}'
            ),
            True,
        ),
        (401, '{"error":"invalid_token"}', True),
        (404, "", False),
        (500, "Keycloak unavailable", False),
        (
            403,
            json.dumps(
                {
                    "error": "insufficient_scope",
                    "error_description": "ProtocolMapper type not allowed",
                    "registrationAccessToken": "fake-registration-token",
                    "access_token": "fake-access-token",
                    "secret": "fake-client-secret",
                }
            ),
            True,
        ),
        (403, '{"registrationAccessToken":"fake-registration-token"}', False),
        (500, "fake-unstructured-token", False),
        (403, '[{"error":"fake-token"}]', False),
        (403, '{"error_description":{"token":"fake-nested-token"}}', False),
    ],
)
def test_http_errors_include_only_error_fields_and_preserve_context(
    method: str, status_code: int, body: str, *, expected_details: bool
) -> None:
    response = httpx2.Response(status_code, text=body)

    def handle_request(_request: httpx2.Request) -> httpx2.Response:
        return response

    with httpx2.Client(
        base_url="https://sso.example.com",
        transport=httpx2.MockTransport(handle_request),
    ) as http:
        raw = RawKeycloakClient(http)
        data = RawClientRepresentation(client_id="my-client")
        with pytest.raises(httpx2.HTTPStatusError) as exc_info:
            match method:
                case "POST":
                    raw.register_client(data)
                case "GET":
                    raw.get_client(
                        client_id=data.client_id, registration_access_token="reg-token"
                    )
                case "PUT":
                    raw.update_client(
                        client_id=data.client_id,
                        registration_access_token="reg-token",
                        data=data,
                    )
                case "DELETE":
                    raw.delete_client(
                        client_id=data.client_id, registration_access_token="reg-token"
                    )

    error = exc_info.value
    assert error.response is response
    assert error.response.status_code == status_code
    assert error.request is response.request
    assert error.request.method == method
    assert str(status_code) in str(error)
    if expected_details:
        detail = str(error).split("Keycloak response: ", 1)[1]
        expected = {
            key: value
            for key, value in json.loads(body).items()
            if key in {"error", "error_description"}
        }
        assert json.loads(detail) == expected
    else:
        assert "Keycloak response:" not in str(error)
    assert "fake-" not in str(error)
