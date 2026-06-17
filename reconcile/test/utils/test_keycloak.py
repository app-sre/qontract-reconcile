import json

import pytest
from pytest_httpserver import HTTPServer

from reconcile.utils.keycloak import (
    KeycloakAPI,
    KeycloakInstance,
    KeycloakMap,
)

KEYCLOAK_DEFAULT_RESPONSE = {
    "clientId": "test-client",
    "secret": "test-secret",
    "registrationAccessToken": "test-rat",
    "redirectUris": ["redirect_uris"],
    "webOrigins": ["https://example.com"],
    "attributes": {},
}


@pytest.fixture
def keycloak_initial_access_token() -> str:
    return "1234567890"


@pytest.fixture
def keycloak_api(
    httpserver: HTTPServer,
    keycloak_initial_access_token: str,
) -> KeycloakAPI:
    return KeycloakAPI(
        url=httpserver.url_for("/"),
        initial_access_token=keycloak_initial_access_token,
    )


def test_keycloak_register_client(
    keycloak_api: KeycloakAPI, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        "/clients-registrations/default", method="post"
    ).respond_with_json(KEYCLOAK_DEFAULT_RESPONSE)

    sso_client = keycloak_api.register_client(
        client_name="test-client",
        redirect_uris=["redirect_uris"],
    )
    assert sso_client.client_id == "test-client"
    assert sso_client.client_secret == "test-secret"
    assert sso_client.registration_access_token == "test-rat"
    assert sso_client.redirect_uris == ["redirect_uris"]
    assert sso_client.issuer == keycloak_api.url
    assert sso_client.attributes == {}

    request = httpserver.log[0][0]
    payload = json.loads(request.data)
    assert payload["clientId"] == "test-client"
    assert payload["redirectUris"] == ["redirect_uris"]
    assert payload["defaultClientScopes"] == [
        "web-origins",
        "acr",
        "profile",
        "roles",
        "email",
    ]
    assert "attributes" not in payload


def test_keycloak_register_client_with_group_filter_regex(
    keycloak_api: KeycloakAPI, httpserver: HTTPServer
) -> None:
    response = {
        **KEYCLOAK_DEFAULT_RESPONSE,
        "attributes": {"group-filter-regex": "^ai-.*"},
    }
    httpserver.expect_request(
        "/clients-registrations/default", method="post"
    ).respond_with_json(response)

    sso_client = keycloak_api.register_client(
        client_name="test-client",
        redirect_uris=["redirect_uris"],
        group_filter_regex="^ai-.*",
    )
    assert sso_client.client_id == "test-client"
    assert sso_client.attributes == {"group-filter-regex": "^ai-.*"}

    request = httpserver.log[0][0]
    payload = json.loads(request.data)
    assert "regex-filtered-groups" in payload["defaultClientScopes"]
    assert payload["attributes"] == {"group-filter-regex": "^ai-.*"}


def test_keycloak_delete_client(
    keycloak_api: KeycloakAPI, httpserver: HTTPServer
) -> None:
    httpserver.expect_request(
        "/client-registration-uri", method="delete"
    ).respond_with_data()
    keycloak_api.delete_client(
        registration_client_uri=httpserver.url_for("/client-registration-uri"),
        registration_access_token="registration_access_token",
    )


def test_keycloak_map_get_client(
    httpserver: HTTPServer,
    keycloak_initial_access_token: str,
) -> None:
    keycloak_url = httpserver.url_for("/")
    keycloak_map = KeycloakMap(
        keycloak_instances=[
            KeycloakInstance(
                url=keycloak_url, initial_access_token=keycloak_initial_access_token
            )
        ]
    )

    assert keycloak_map.get(keycloak_url).url == keycloak_url
    assert (
        keycloak_map.get(keycloak_url).initial_access_token
        == keycloak_initial_access_token
    )

    with pytest.raises(KeyError):
        keycloak_map.get("non-existent-keycloak-url")
