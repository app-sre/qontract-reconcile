import json

import httpretty as httpretty_module
import pytest

from reconcile.utils.keycloak import (
    KeycloakAPI,
    KeycloakInstance,
    KeycloakMap,
)


@pytest.fixture
def keycloak_url() -> str:
    return "http://fake-keycloak-server.com"


@pytest.fixture
def keycloak_initial_access_token() -> str:
    return "1234567890"


@pytest.fixture
def keycloak_openid_configuration_fake(
    httpretty: httpretty_module, keycloak_url: str
) -> None:
    httpretty.register_uri(
        httpretty.GET,
        f"{keycloak_url}/.well-known/openid-configuration",
        body=json.dumps(
            {
                # no other fields are in use currently
                "registration_endpoint": f"{keycloak_url}/clients-registrations/openid-connect",
            }
        ),
        content_type="text/json",
    )


@pytest.fixture
def keycloak_api(
    keycloak_url: str,
    keycloak_initial_access_token: str,
    keycloak_openid_configuration_fake: None,
) -> KeycloakAPI:
    return KeycloakAPI(
        url=keycloak_url, initial_access_token=keycloak_initial_access_token
    )


def test_keycloak_register_client(
    keycloak_api: KeycloakAPI, httpretty: httpretty_module
) -> None:
    httpretty.register_uri(
        httpretty.POST,
        f"{keycloak_api._openid_configuration['registration_endpoint']}",
        body=json.dumps(
            {
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
            }
        ),
        content_type="text/json",
    )
    sso_client = keycloak_api.register_client(
        client_name="test-client",
        redirect_uris=["redirect_uris"],
        initiate_login_uri="initiate_login_uri",
        request_uris=["request_uris"],
        contacts=["contact"],
    )
    assert httpretty.last_request().headers
    assert sso_client.issuer == keycloak_api.url


def test_keycloak_delete_client(
    keycloak_api: KeycloakAPI, httpretty: httpretty_module, keycloak_url: str
) -> None:
    httpretty.register_uri(httpretty.DELETE, f"{keycloak_url}/client-registration-uri")
    keycloak_api.delete_client(
        registration_client_uri=f"{keycloak_url}/client-registration-uri",
        registration_access_token="registration_access_token",
    )
    assert httpretty.last_request().headers


def test_keycloak_map_get_client(
    keycloak_openid_configuration_fake: None,
    keycloak_url: str,
    keycloak_initial_access_token: str,
) -> None:
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
