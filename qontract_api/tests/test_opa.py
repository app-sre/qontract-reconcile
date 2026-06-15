"""Tests for OPA client and authorization."""

import re
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpxyz as httpx
import pytest
from fastapi import HTTPException

from qontract_api.opa import OPAClient, flatten_params

# ── flatten_params ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param(
            {"a": "1", "b": "2"},
            {"a": "1", "b": "2"},
            id="flat",
        ),
        pytest.param(
            {"secret": {"path": "x", "server_url": "y"}},
            {"secret.path": "x", "secret.server_url": "y"},
            id="nested",
        ),
        pytest.param(
            {"a": {"b": {"c": "deep"}}},
            {"a.b.c": "deep"},
            id="deep-nesting",
        ),
        pytest.param(
            {"a": "1", "b": None, "c": "3"},
            {"a": "1", "c": "3"},
            id="none-skipped",
        ),
        pytest.param(
            {"usernames": ["alice", "bob"], "key": "val"},
            {"key": "val"},
            id="list-skipped",
        ),
        pytest.param(
            {"version": 42, "enabled": True},
            {"version": "42", "enabled": "True"},
            id="scalars-to-string",
        ),
        pytest.param({}, {}, id="empty"),
        pytest.param(
            {
                "usernames": ["alice", "bob"],
                "secret": {
                    "secret_manager_url": "https://vault.example.com",
                    "path": "app-sre/creds/ldap",
                    "field": None,
                    "version": None,
                    "server_url": "ldap://freeipa.example.com",
                    "base_dn": "dc=example,dc=com",
                },
            },
            {
                "secret.secret_manager_url": "https://vault.example.com",
                "secret.path": "app-sre/creds/ldap",
                "secret.server_url": "ldap://freeipa.example.com",
                "secret.base_dn": "dc=example,dc=com",
            },
            id="realistic-ldap-body",
        ),
        pytest.param(
            {
                "workspace_name": "redhat-internal",
                "channel": "dev-null",
                "text": "hello",
                "secret": {
                    "secret_manager_url": "https://vault.example.com",
                    "path": "app-sre/creds/slack",
                    "field": "token",
                    "version": None,
                },
            },
            {
                "workspace_name": "redhat-internal",
                "channel": "dev-null",
                "text": "hello",
                "secret.secret_manager_url": "https://vault.example.com",
                "secret.path": "app-sre/creds/slack",
                "secret.field": "token",
            },
            id="realistic-slack-body",
        ),
    ],
)
def test_flatten_params(data: dict[str, Any], expected: dict[str, str]) -> None:
    assert flatten_params(data) == expected


# ── OPAClient URL construction ──────────────────────────────────


@pytest.mark.parametrize(
    ("host", "package_name", "expected_opa_url", "expected_health_url"),
    [
        pytest.param(
            "http://opa:8181",
            "authz",
            "http://opa:8181/v1/data/authz",
            "http://opa:8181/health",
            id="simple",
        ),
        pytest.param(
            "http://opa:8181/",
            "authz",
            "http://opa:8181/v1/data/authz",
            "http://opa:8181/health",
            id="trailing-slash",
        ),
        pytest.param(
            "http://opa:8181",
            "authz.rbac",
            "http://opa:8181/v1/data/authz/rbac",
            "http://opa:8181/health",
            id="dotted-package",
        ),
    ],
)
def test_opa_client_urls(
    host: str,
    package_name: str,
    expected_opa_url: str,
    expected_health_url: str,
) -> None:
    client = OPAClient(
        host=host,
        package_name=package_name,
        skip_endpoints=[],
        client=httpx.AsyncClient(),
    )
    assert client.opa_url == expected_opa_url
    assert client.health_url == expected_health_url


# ── OPAClient.should_skip ────────────────────────────────────────


@pytest.fixture
def opa_client() -> OPAClient:
    return OPAClient(
        host="http://opa:8181",
        package_name="authz",
        skip_endpoints=[re.compile(r"^/health/.*"), re.compile(r"^/docs.*")],
        client=httpx.AsyncClient(),
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health/ready", True),
        ("/docs", True),
        ("/docs/openapi.json", True),
        ("/api/v1/external/ldap/users/check", False),
        ("/metrics", False),
    ],
)
def test_should_skip(opa_client: OPAClient, path: str, expected: bool) -> None:
    assert opa_client.should_skip(path) is expected


# ── OPAClient.authorize ─────────────────────────────────────────


def _mock_response(*, status_code: int = 200, json_data: dict | None = None) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    return response


def _make_client(mock: AsyncMock) -> OPAClient:
    return OPAClient(
        host="http://opa:8181",
        package_name="authz",
        skip_endpoints=[],
        client=mock,
    )


@pytest.mark.anyio
async def test_authorize_allowed() -> None:
    mock = AsyncMock()
    mock.post.return_value = _mock_response(
        json_data={"result": {"authorized": True, "objects": ["ldap-users-check"]}}
    )
    await _make_client(mock).authorize(
        username="ldap-users-api",
        obj="ldap-users-check",
        params={"secret.path": "app-sre/creds/ldap"},
    )


@pytest.mark.parametrize(
    ("response", "description"),
    [
        pytest.param(
            _mock_response(json_data={"result": {"authorized": False}}),
            "denied",
            id="denied",
        ),
        pytest.param(
            _mock_response(status_code=500),
            "opa-error",
            id="opa-http-error",
        ),
        pytest.param(
            _mock_response(json_data={"result": {}}),
            "empty-result",
            id="empty-result",
        ),
    ],
)
@pytest.mark.anyio
async def test_authorize_returns_403(response: Mock, description: str) -> None:
    mock = AsyncMock()
    mock.post.return_value = response
    with pytest.raises(HTTPException) as exc_info:
        await _make_client(mock).authorize(
            username="user",
            obj="some-endpoint",
            params={},
        )
    assert exc_info.value.status_code == 403, description


@pytest.mark.anyio
async def test_authorize_connection_error_returns_403() -> None:
    mock = AsyncMock()
    mock.post.side_effect = httpx.ConnectError("connection refused")
    with pytest.raises(HTTPException) as exc_info:
        await _make_client(mock).authorize(
            username="user",
            obj="some-endpoint",
            params={},
        )
    assert exc_info.value.status_code == 403
