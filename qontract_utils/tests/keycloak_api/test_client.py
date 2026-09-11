"""Tests for qontract_utils.keycloak_api.client."""

from unittest.mock import MagicMock

import httpx2
import pytest
from pytest_httpserver import HTTPServer
from qontract_utils.hooks import Hooks
from qontract_utils.keycloak_api import KeycloakApi
from qontract_utils.keycloak_api.models import ManagedKeycloakClient

REGISTER_PATH = "/clients-registrations/default"


def _make_api(httpserver: HTTPServer, initial_access_token: str) -> KeycloakApi:
    return KeycloakApi(
        url=httpserver.url_for(""),
        initial_access_token=initial_access_token,
        timeout=5,
    )


def _managed_client(**overrides: object) -> ManagedKeycloakClient:
    defaults: dict[str, object] = {
        "client_id": "my-app-my-client",
        "redirect_uris": ["https://example.com/callback"],
    }
    return ManagedKeycloakClient.model_validate({**defaults, **overrides})


#
# register_client
#


def test_register_client_sends_correct_body_and_auth(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        {
            "clientId": "my-client",
            "secret": "s3cr3t",
            "redirectUris": ["https://example.com/callback"],
            "registrationAccessToken": "reg-token",
        }
    )

    api.register_client(
        ManagedKeycloakClient(
            client_id="my-client", redirect_uris=["https://example.com/callback"]
        )
    )

    requests = [req for req, _ in httpserver.log if req.path == REGISTER_PATH]
    assert len(requests) == 1
    request = requests[0]
    assert request.headers["Authorization"] == "Bearer initial-token"
    body = request.get_json()
    assert body["clientId"] == "my-client"
    assert body["redirectUris"] == ["https://example.com/callback"]


def test_default_user_agent_identifies_qontract_utils(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        {
            "clientId": "my-client",
            "secret": "s3cr3t",
            "registrationAccessToken": "reg-token",
        }
    )

    api.register_client(_managed_client())

    request = next(req for req, _ in httpserver.log if req.path == REGISTER_PATH)
    assert request.headers["User-Agent"].startswith("qontract-utils/")


def test_custom_user_agent_overrides_default(httpserver: HTTPServer) -> None:
    api = KeycloakApi(
        url=httpserver.url_for(""),
        initial_access_token="initial-token",
        timeout=5,
        user_agent="qontract-api/1.2.3",
    )
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        {
            "clientId": "my-client",
            "secret": "s3cr3t",
            "registrationAccessToken": "reg-token",
        }
    )

    api.register_client(_managed_client())

    request = next(req for req, _ in httpserver.log if req.path == REGISTER_PATH)
    assert request.headers["User-Agent"] == "qontract-api/1.2.3"


def test_register_client_maps_response_to_domain_model(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        {
            "clientId": "my-client",
            "secret": "s3cr3t",
            "redirectUris": ["https://example.com/callback"],
            "registrationAccessToken": "reg-token",
        }
    )

    result = api.register_client(_managed_client(client_id="my-client"))

    assert result.client_id == "my-client"
    assert result.secret == "s3cr3t"
    assert result.redirect_uris == ["https://example.com/callback"]
    assert result.registration_access_token == "reg-token"


def test_register_client_folds_and_sends_extra_attributes(
    httpserver: HTTPServer,
) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    httpserver.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        {
            "clientId": "my-client",
            "secret": "s3cr3t",
            "registrationAccessToken": "reg-token",
        }
    )

    api.register_client(
        _managed_client(
            default_client_scopes=["web-origins", "regex-filtered-groups"],
            extra_attributes={"group-filter-regex": "^my-group-.*$"},
        )
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
        {
            "clientId": "c1",
            "secret": "s3cr3t-1",
            "redirectUris": ["https://example.com/cb"],
            "registrationAccessToken": "reg-token-1",
        }
    )
    httpserver_ipv4.expect_request(REGISTER_PATH, method="POST").respond_with_json(
        {
            "clientId": "c2",
            "secret": "s3cr3t-2",
            "redirectUris": ["https://example.com/cb"],
            "registrationAccessToken": "reg-token-2",
        }
    )

    api1.register_client(
        _managed_client(client_id="c1", redirect_uris=["https://example.com/cb"])
    )
    api2.register_client(
        _managed_client(client_id="c2", redirect_uris=["https://example.com/cb"])
    )

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


#
# require_https (SSRF guard)
#


def test_require_https_rejects_plain_http() -> None:
    with pytest.raises(ValueError, match="must use https://"):
        KeycloakApi(
            url="http://keycloak.example.com",
            initial_access_token="initial-token",
            require_https=True,
        )


def test_require_https_allows_https() -> None:
    api = KeycloakApi(
        url="https://keycloak.example.com",
        initial_access_token="initial-token",
        require_https=True,
    )
    assert api.url == "https://keycloak.example.com"


def test_require_https_defaults_to_false(httpserver: HTTPServer) -> None:
    # httpserver only serves plain http:// - this must not raise without require_https.
    _make_api(httpserver, initial_access_token="initial-token")


# Fetching and updating a managed client


def test_get_client_uses_registration_access_token(
    httpserver: HTTPServer,
) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    get_path = f"{REGISTER_PATH}/my-client"
    httpserver.expect_request(get_path, method="GET").respond_with_json(
        {
            "clientId": "my-client",
            "redirectUris": ["https://example.com/callback"],
        }
    )

    result = api.get_client(
        client_id="my-client", registration_access_token="reg-token"
    )

    request = next(req for req, _ in httpserver.log if req.path == get_path)
    assert request.headers["Authorization"] == "Bearer reg-token"
    assert result.client_id == "my-client"


def test_update_client_returns_rotated_token(httpserver: HTTPServer) -> None:
    api = _make_api(httpserver, initial_access_token="initial-token")
    update_path = f"{REGISTER_PATH}/my-client"
    httpserver.expect_request(update_path, method="PUT").respond_with_json(
        {
            "clientId": "my-client",
            "redirectUris": ["https://example.com/callback", "https://example.com/cb2"],
            "registrationAccessToken": "new-reg-token",
        }
    )

    result = api.update_client(
        client_id="my-client",
        registration_access_token="old-reg-token",
        data=_managed_client(
            client_id="my-client",
            redirect_uris=[
                "https://example.com/callback",
                "https://example.com/cb2",
            ],
        ),
    )

    request = next(req for req, _ in httpserver.log if req.path == update_path)
    assert request.headers["Authorization"] == "Bearer old-reg-token"
    assert result.registration_access_token == "new-reg-token"
