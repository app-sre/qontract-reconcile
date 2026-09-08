"""Tests for the GitHub org members router endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
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


MEMBERS_ENDPOINT = "/api/v1/external/github-org/members"

QUERY_PARAMS = {
    "org_name": "my-org",
    "secret_manager_url": "https://vault.example.com",
    "path": "secret/github/my-org",
    "field": "token",
}


@patch("qontract_api.external.github_org.router.GithubOrgClientFactory")
def test_get_org_members_returns_members(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /members returns all org members (case preserved)."""
    mock_client = MagicMock()
    mock_client.get_all_members.return_value = ["Bob", "alice", "Charlie"]
    mock_factory.return_value.create_workspace_client.return_value = mock_client

    response = api_client.get(
        MEMBERS_ENDPOINT,
        params=QUERY_PARAMS,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["members"] == ["Bob", "alice", "Charlie"]
    mock_client.get_all_members.assert_called_once_with("my-org")


@patch("qontract_api.external.github_org.router.GithubOrgClientFactory")
def test_get_org_members_resolves_token_from_secret(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """The GitHub token is resolved from the Vault secret reference."""
    mock_client = MagicMock()
    mock_client.get_all_members.return_value = []
    mock_factory.return_value.create_workspace_client.return_value = mock_client

    api_client.get(MEMBERS_ENDPOINT, params=QUERY_PARAMS, headers=auth_headers)

    # secret_manager.read(params) is used to resolve the token
    api_client.app.state.secret_manager.read.assert_called_once()
    read_arg = api_client.app.state.secret_manager.read.call_args[0][0]
    assert read_arg.path == "secret/github/my-org"
    assert read_arg.org_name == "my-org"


def test_get_org_members_requires_auth(api_client: TestClient) -> None:
    """Requests without a valid token are rejected."""
    response = api_client.get(MEMBERS_ENDPOINT, params=QUERY_PARAMS)
    assert response.status_code in {
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
    }
