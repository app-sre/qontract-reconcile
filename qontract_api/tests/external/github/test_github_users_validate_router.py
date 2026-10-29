"""Tests for the GitHub users validate router endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from qontract_utils.github_api import GithubUser

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


VALIDATE_ENDPOINT = "/api/v1/external/github/users/validate"

REQUEST_BODY = {
    "secret": {
        "secret_manager_url": "https://vault.example.com",
        "path": "secret/github/token",
        "field": "token",
    },
    "usernames": ["chunxialexluo", "mnovak1"],
}


@patch("qontract_api.external.github.router.GithubClientFactory")
def test_validate_users_returns_canonical_logins(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Returns canonical login and type for each resolved username."""
    mock_client = MagicMock()
    mock_client.lookup_users.return_value = [
        GithubUser(login="ChunxiAlexLuo", type="User", id=1)
    ]
    mock_factory.return_value.create_user_workspace_client.return_value = mock_client

    response = api_client.post(
        VALIDATE_ENDPOINT,
        json=REQUEST_BODY,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["users"] == [{"login": "ChunxiAlexLuo", "type": "User"}]
    mock_client.lookup_users.assert_called_once_with(["chunxialexluo", "mnovak1"])


@patch("qontract_api.external.github.router.GithubClientFactory")
def test_validate_users_omits_nonexistent(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A username that doesn't exist on GitHub is omitted from the response."""
    mock_client = MagicMock()
    mock_client.lookup_users.return_value = []
    mock_factory.return_value.create_user_workspace_client.return_value = mock_client

    response = api_client.post(
        VALIDATE_ENDPOINT,
        json=REQUEST_BODY,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["users"] == []


@patch("qontract_api.external.github.router.GithubClientFactory")
def test_validate_users_filters_by_account_type(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """When account_type is set, accounts of another type are excluded."""
    mock_client = MagicMock()
    mock_client.lookup_users.return_value = [
        GithubUser(login="alice", type="User", id=1),
        GithubUser(login="app-sre", type="Organization", id=2),
    ]
    mock_factory.return_value.create_user_workspace_client.return_value = mock_client

    response = api_client.post(
        VALIDATE_ENDPOINT,
        json={**REQUEST_BODY, "account_type": "User"},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["users"] == [{"login": "alice", "type": "User"}]


@patch("qontract_api.external.github.router.GithubClientFactory")
def test_validate_users_without_account_type_returns_all(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """When account_type is unset, both users and organizations are returned."""
    mock_client = MagicMock()
    mock_client.lookup_users.return_value = [
        GithubUser(login="alice", type="User", id=1),
        GithubUser(login="app-sre", type="Organization", id=2),
    ]
    mock_factory.return_value.create_user_workspace_client.return_value = mock_client

    response = api_client.post(
        VALIDATE_ENDPOINT,
        json=REQUEST_BODY,
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["users"] == [
        {"login": "alice", "type": "User"},
        {"login": "app-sre", "type": "Organization"},
    ]


@patch("qontract_api.external.github.router.GithubClientFactory")
def test_validate_users_resolves_token_from_secret(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """The GitHub token is resolved from the Vault secret reference, not org_username."""
    mock_client = MagicMock()
    mock_client.lookup_users.return_value = []
    mock_factory.return_value.create_user_workspace_client.return_value = mock_client

    from qontract_api.main import app

    api_client.post(VALIDATE_ENDPOINT, json=REQUEST_BODY, headers=auth_headers)

    app.state.secret_manager.read.assert_called_once()
    read_arg = app.state.secret_manager.read.call_args[0][0]
    assert read_arg.path == "secret/github/token"


def test_validate_users_requires_auth(api_client: TestClient) -> None:
    """Requests without a valid token are rejected."""
    response = api_client.post(VALIDATE_ENDPOINT, json=REQUEST_BODY)
    assert response.status_code in {
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
    }
