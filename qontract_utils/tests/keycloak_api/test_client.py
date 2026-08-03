"""Tests for qontract_utils.keycloak_api.client."""

from unittest.mock import MagicMock

import httpx2
import pytest
from pytest_httpserver import HTTPServer
from qontract_utils.hooks import Hooks
from qontract_utils.keycloak_api import KeycloakApi

REGISTER_PATH = "/clients-registrations/default"


def _registration_response(
    client_id: str,
    secret: str,
    redirect_uris: list[str],
    registration_access_token: str,
) -> dict[str, object]:
    return {
        "clientId": client_id,
        "secret": secret,
        "redirectUris": redirect_uris,
        "registrationAccessToken": registration_access_token,
    }


def _make_api(httpserver: HTTPServer, initial_access_token: str) -> KeycloakApi:
    return KeycloakApi(
        url=httpserver.url_for(""),
        initial_access_token=initial_access_token,
        timeout=5,
    )


#
# register_client
#


def test_register_client_sends_correct_body_and_auth(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        _registration_response(
            client_id="my-client",
            secret="s3cr3t",
            redirect_uris=["https://example.com/callback"],
            registration_access_token="reg-token",
        )
    )

    api.register_client(
        client_name="my-client", redirect_uris=["https://example.com/callback"]
    )

    requests = [req for req, _ in httpserver.log if req.path == REGISTER_PATH]
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["Authorization"] == "Bearer initial-token"
    body = request.get_json()
    assert body["clientId"] == "my-client"
    assert body["redirectUris"] == ["https://example.com/callback"]
    assert body["defaultClientScopes"] == [
        "web-origins",
        "acr",
        "profile",
        "roles",
        "email",
    ]
    assert "attributes" not in body or body["attributes"] is None


def test_register_client_maps_response_to_domain_model(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        _registration_response(
            client_id="my-client",
            secret="s3cr3t",
            redirect_uris=["https://example.com/callback"],
            registration_access_token="reg-token",
        )
    )

    sso_client = api.register_client(
        client_name="my-client", redirect_uris=["https://example.com/callback"]
    )

    assert sso_client.client_id == "my-client"
    assert sso_client.client_secret == "s3cr3t"
    assert sso_client.redirect_uris == ["https://example.com/callback"]
    assert sso_client.registration_access_token == "reg-token"


def test_register_client_with_group_filter_regex(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        _registration_response(
            client_id="my-client",
            secret="s3cr3t",
            redirect_uris=["https://example.com/callback"],
            registration_access_token="reg-token",
        )
    )

    api.register_client(
        client_name="my-client",
        redirect_uris=["https://example.com/callback"],
        group_filter_regex="^my-group-.*$",
    )

    request = next(req for req, _ in httpserver.log if req.path == REGISTER_PATH)
    body = request.get_json()
    assert "regex-filtered-groups" in body["defaultClientScopes"]
    assert body["attributes"] == {"group-filter-regex": "^my-group-.*$"}


#
# delete_client
#


def test_delete_client_uses_registration_access_token(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    delete_path = f"{REGISTER_PATH}/my-client"
    httpserver.expect_request(delete_path, method="DELETE").respond_with_data(
        status=204
    )

    api.delete_client(client_id="my-client", registration_access_token="reg-token")

    requests = [req for req, _ in httpserver.log if req.path == delete_path]
    assert len(requests) == 1
    # The per-client registration token is used, NOT the realm's initial_access_token -
    # proves clientele's per-call `headers=` override actually overrides.
    assert requests[0].headers["Authorization"] == "Bearer reg-token"


def test_delete_client_raises_on_error(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    delete_path = f"{REGISTER_PATH}/missing-client"
    httpserver.expect_request(delete_path, method="DELETE").respond_with_data(
        status=404
    )

    with pytest.raises(httpx2.HTTPStatusError) as exc_info:
        api.delete_client(
            client_id="missing-client", registration_access_token="reg-token"
        )
    assert exc_info.value.response.status_code == 404


#
# per-instance isolation
#


def test_two_instances_do_not_share_state(
    httpserver: HTTPServer, httpserver_ipv4: HTTPServer
) -> None:
    api1 = _make_api(httpserver, initial_access_token="token-1")
    api2 = _make_api(httpserver_ipv4, initial_access_token="token-2")
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        _registration_response(
            client_id="c1",
            secret="s3cr3t-1",
            redirect_uris=["https://example.com/cb"],
            registration_access_token="reg-token-1",
        )
    )
    httpserver_ipv4.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        _registration_response(
            client_id="c2",
            secret="s3cr3t-2",
            redirect_uris=["https://example.com/cb"],
            registration_access_token="reg-token-2",
        )
    )

    api1.register_client(client_name="c1", redirect_uris=["https://example.com/cb"])
    api2.register_client(client_name="c2", redirect_uris=["https://example.com/cb"])

    req1 = next(req for req, _ in httpserver.log if req.path == REGISTER_PATH)
    req2 = next(req for req, _ in httpserver_ipv4.log if req.path == REGISTER_PATH)
    assert req1.headers["Authorization"] == "Bearer token-1"
    assert req2.headers["Authorization"] == "Bearer token-2"
    assert api1.url != api2.url


#
# lifecycle
#


def test_context_manager_closes_client(httpserver: HTTPServer) -> None:
    with _make_api(httpserver, initial_access_token="initial-token") as api:
        assert not api._client.is_closed
    assert api._client.is_closed


#
# hooks
#


def test_pre_hooks_includes_metrics(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")

    assert len(api._hooks.pre_hooks) >= 1


def test_custom_hooks_appended_after_builtin(httpserver: HTTPServer) -> None:
    custom_hook = MagicMock()

    api = KeycloakApi(
        url=httpserver.url_for(""),
        initial_access_token="initial-token",
        hooks=Hooks(pre_hooks=[custom_hook]),
        timeout=5,
    )

    assert custom_hook in api._hooks.pre_hooks
    # built-in: metrics, request_log, latency_start = 3, + 1 custom = 4
    assert len(api._hooks.pre_hooks) == 4
