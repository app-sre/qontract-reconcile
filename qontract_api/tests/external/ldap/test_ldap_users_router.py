"""Tests for LDAP users check router endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.external.ldap.schemas import LdapUserStatus
from qontract_api.models import TokenData


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    """Create test client with mocked cache and secret_manager."""
    from qontract_api.main import app

    app.state.cache = Mock()
    app.state.secret_manager = Mock()

    yield TestClient(app, raise_server_exceptions=False)

    if hasattr(app.state, "cache"):
        del app.state.cache
    if hasattr(app.state, "secret_manager"):
        del app.state.secret_manager


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


LDAP_USERS_CHECK_ENDPOINT = "/api/v1/external/ldap/users/check"

LDAP_USERS_CHECK_REQUEST = {
    "usernames": ["alice", "bob", "charlie"],
    "secret": {
        "secret_manager_url": "https://vault.example.com",
        "path": "secret/ldap/freeipa",
        "field": "bind_password",
        "server_url": "ldap://freeipa.example.com",
        "base_dn": "dc=example,dc=com",
    },
}


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_check_users_exist_returns_status(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /users/check returns existence status per username."""
    mock_client = MagicMock()
    mock_client.check_users_exist.return_value = [
        LdapUserStatus(username="alice", exists=True),
        LdapUserStatus(username="bob", exists=True),
        LdapUserStatus(username="charlie", exists=False),
    ]
    mock_factory.return_value = mock_client

    response = api_client.post(
        LDAP_USERS_CHECK_ENDPOINT,
        json=LDAP_USERS_CHECK_REQUEST,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert len(data["users"]) == 3
    users_by_name = {u["username"]: u["exists"] for u in data["users"]}
    assert users_by_name == {"alice": True, "bob": True, "charlie": False}


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_check_users_exist_calls_factory_with_secret(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /users/check passes secret to factory correctly."""
    mock_client = MagicMock()
    mock_client.check_users_exist.return_value = []
    mock_factory.return_value = mock_client

    api_client.post(
        LDAP_USERS_CHECK_ENDPOINT,
        json={
            "usernames": [],
            "secret": LDAP_USERS_CHECK_REQUEST["secret"],
        },
        headers=auth_headers,
    )

    mock_factory.assert_called_once()
    call_kwargs = mock_factory.call_args.kwargs
    assert call_kwargs["secret"].server_url == "ldap://freeipa.example.com"
    assert call_kwargs["secret"].base_dn == "dc=example,dc=com"
    assert call_kwargs["secret"].path == "secret/ldap/freeipa"


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_check_users_exist_empty_list(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /users/check with empty usernames list."""
    mock_client = MagicMock()
    mock_client.check_users_exist.return_value = []
    mock_factory.return_value = mock_client

    response = api_client.post(
        LDAP_USERS_CHECK_ENDPOINT,
        json={
            "usernames": [],
            "secret": LDAP_USERS_CHECK_REQUEST["secret"],
        },
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["users"] == []
