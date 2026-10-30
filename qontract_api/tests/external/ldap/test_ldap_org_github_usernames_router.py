"""Tests for LDAP org-github-usernames resolution router endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.external.ldap.schemas import (
    LdapDirectSecret,
    LdapOrgGithubUsernamesRequest,
)
from qontract_api.models import TokenData


@pytest.fixture
def api_client() -> Generator[TestClient]:
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


LDAP_ORG_GITHUB_USERNAMES_ENDPOINT = "/api/v1/external/ldap/org-github-usernames"

LDAP_SECRET = LdapDirectSecret(
    secret_manager_url="https://vault.example.com",
    path="secret/ldap/freeipa",
    field="bind_password",
    server_urls=["ldap://freeipa.example.com", "ldap://replica.example.com"],
    base_dn="dc=example,dc=com",
)

LDAP_ORG_GITHUB_USERNAMES_REQUEST = LdapOrgGithubUsernamesRequest(
    secret=LDAP_SECRET,
).model_dump(mode="json")


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_resolve_org_github_usernames_returns_pairs(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /org-github-usernames returns resolved org_username -> github_username."""
    mock_client = MagicMock()
    mock_client.get_org_username_to_github_map.return_value = {
        "alice": "alicegh",
        "bob": "bobgh",
    }
    mock_factory.return_value = mock_client

    response = api_client.post(
        LDAP_ORG_GITHUB_USERNAMES_ENDPOINT,
        json=LDAP_ORG_GITHUB_USERNAMES_REQUEST,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    resolved = {u["org_username"]: u["github_username"] for u in data["users"]}
    assert resolved == {"alice": "alicegh", "bob": "bobgh"}
    mock_client.get_org_username_to_github_map.assert_called_once_with()


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_resolve_org_github_usernames_passes_secret(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /org-github-usernames passes the Vault secret to the factory."""
    mock_client = MagicMock()
    mock_client.get_org_username_to_github_map.return_value = {}
    mock_factory.return_value = mock_client

    api_client.post(
        LDAP_ORG_GITHUB_USERNAMES_ENDPOINT,
        json=LDAP_ORG_GITHUB_USERNAMES_REQUEST,
        headers=auth_headers,
    )

    mock_factory.assert_called_once()
    call_kwargs = mock_factory.call_args.kwargs
    assert call_kwargs["secret"].server_urls == [
        "ldap://freeipa.example.com",
        "ldap://replica.example.com",
    ]
    assert call_kwargs["secret"].base_dn == "dc=example,dc=com"
    assert call_kwargs["secret"].path == "secret/ldap/freeipa"


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_resolve_org_github_usernames_empty_result(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /org-github-usernames returns an empty list when nothing resolves."""
    mock_client = MagicMock()
    mock_client.get_org_username_to_github_map.return_value = {}
    mock_factory.return_value = mock_client

    response = api_client.post(
        LDAP_ORG_GITHUB_USERNAMES_ENDPOINT,
        json=LDAP_ORG_GITHUB_USERNAMES_REQUEST,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["users"] == []
