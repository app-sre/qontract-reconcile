from urllib.parse import urlparse

import pytest
from pytest_httpserver import HTTPServer

from reconcile.utils.keycloak import (
    KeycloakAPI,
    KeycloakInstance,
    KeycloakMap,
)


@pytest.fixture
def keycloak_initial_access_token() -> str:
    return "1234567890"


@pytest.fixture
def keycloak_openid_configuration_setup(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/.well-known/openid-configuration").respond_with_json({
        # no other fields are in use currently
        "registration_endpoint": httpserver.url_for(
            "/clients-registrations/openid-connect"
        ),
    })


@pytest.fixture
def keycloak_api(
    httpserver: HTTPServer,
    keycloak_initial_access_token: str,
    keycloak_openid_configuration_setup: None,
) -> KeycloakAPI:
    return KeycloakAPI(
        url=httpserver.url_for("/"), initial_access_token=keycloak_initial_access_token
    )


def test_keycloak_register_client(
    keycloak_api: KeycloakAPI, httpserver: HTTPServer
) -> None:
    url = urlparse(keycloak_api._openid_configuration["registration_endpoint"])  # type: ignore[index]
    httpserver.expect_request(url.path, method="post").respond_with_json({
        "client_id": "test-client",
        "client_id_issued_at": 0,
        "client_name": "str",
        "client_secret": "str",
        "client_secret_expires_at": 0,
        "grant_types": ["just-a-string"],
        "redirect_uris": ["just-a-string"],
        "registration_access_token": "str",
        "registration_client_uri": "str",
        "request_uris": ["just-a-string"],
        "response_types": ["just-a-string"],
        "subject_type": "str",
        "tls_client_certificate_bound_access_tokens": False,
        "token_endpoint_auth_method": "str",
    })
    sso_client = keycloak_api.register_client(
        client_name="test-client",
        redirect_uris=["redirect_uris"],
        initiate_login_uri="initiate_login_uri",
        request_uris=["request_uris"],
        contacts=["contact"],
    )
    assert sso_client.issuer == keycloak_api.url


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
    keycloak_openid_configuration_setup: None,
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
