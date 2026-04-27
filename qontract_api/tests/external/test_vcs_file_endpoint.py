"""Tests for VCS file read endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.models import TokenData


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create authentication headers with valid JWT token."""
    token_data = TokenData(sub="testuser")
    test_token = create_access_token(data=token_data)
    return {"Authorization": f"Bearer {test_token}"}


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


VCS_FILE_ENDPOINT = "/api/v1/external/vcs/repos/file"

VCS_SECRET_PARAMS = {
    "secret_manager_url": "https://vault.example.com",
    "path": "secret/vcs/token",
    "field": "token",
    "repo_url": "https://gitlab.example.com/group/project",
    "file_path": "data/users/alice.yml",
    "ref": "master",
}


@patch("qontract_api.external.vcs.router.create_vcs_workspace_client")
def test_get_file_returns_content(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /repos/file returns file content."""
    mock_client = MagicMock()
    mock_client.get_file.return_value = "name: alice\nemail: alice@example.com"
    mock_factory.return_value = mock_client

    response = api_client.get(
        VCS_FILE_ENDPOINT, params=VCS_SECRET_PARAMS, headers=auth_headers
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["content"] == "name: alice\nemail: alice@example.com"
    mock_client.get_file.assert_called_once_with(
        path="data/users/alice.yml", ref="master"
    )


@patch("qontract_api.external.vcs.router.create_vcs_workspace_client")
def test_get_file_returns_404_when_not_found(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /repos/file returns 404 when file not found."""
    mock_client = MagicMock()
    mock_client.get_file.return_value = None
    mock_factory.return_value = mock_client

    response = api_client.get(
        VCS_FILE_ENDPOINT, params=VCS_SECRET_PARAMS, headers=auth_headers
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@patch("qontract_api.external.vcs.router.create_vcs_workspace_client")
def test_get_file_passes_secret_to_factory(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /repos/file passes secret to factory correctly."""
    mock_client = MagicMock()
    mock_client.get_file.return_value = "content"
    mock_factory.return_value = mock_client

    api_client.get(VCS_FILE_ENDPOINT, params=VCS_SECRET_PARAMS, headers=auth_headers)

    mock_factory.assert_called_once()
    call_kwargs = mock_factory.call_args.kwargs
    assert call_kwargs["repo_url"] == "https://gitlab.example.com/group/project"
