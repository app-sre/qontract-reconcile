"""Tests for VCS merge request router endpoints (find + create)."""

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


FIND_MR_ENDPOINT = "/api/v1/external/vcs/merge-requests"
CREATE_MR_ENDPOINT = "/api/v1/external/vcs/merge-requests"

FIND_MR_PARAMS = {
    "secret_manager_url": "https://vault.example.com",
    "path": "secret/vcs/token",
    "field": "token",
    "repo_url": "https://gitlab.example.com/group/project",
    "title": "[ldap-users] delete user alice",
}

CREATE_MR_REQUEST = {
    "repo_url": "https://gitlab.example.com/group/project",
    "token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "secret/vcs/token",
        "field": "token",
    },
    "title": "[ldap-users] delete user alice",
    "description": "delete user alice",
    "file_operations": [
        {
            "path": "data/users/alice.yml",
            "action": "delete",
            "commit_message": "delete user alice",
        },
    ],
    "auto_merge": True,
}


# --- find_merge_request ---


@patch("qontract_api.external.vcs.router.create_vcs_workspace_client")
def test_find_merge_request_found(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /merge-requests returns MR URL when found."""
    mock_client = MagicMock()
    mock_client.find_merge_request.return_value = "https://gitlab.com/mr/42"
    mock_factory.return_value = mock_client

    response = api_client.get(
        FIND_MR_ENDPOINT, params=FIND_MR_PARAMS, headers=auth_headers
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["url"] == "https://gitlab.com/mr/42"
    mock_client.find_merge_request.assert_called_once_with(
        "[ldap-users] delete user alice"
    )


@patch("qontract_api.external.vcs.router.create_vcs_workspace_client")
def test_find_merge_request_not_found(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test GET /merge-requests returns 404 when no MR found."""
    mock_client = MagicMock()
    mock_client.find_merge_request.return_value = None
    mock_factory.return_value = mock_client

    response = api_client.get(
        FIND_MR_ENDPOINT, params=FIND_MR_PARAMS, headers=auth_headers
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


# --- create_merge_request ---


@patch("qontract_api.external.vcs.router.create_vcs_workspace_client")
def test_create_merge_request_success(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /merge-requests creates MR and returns URL."""
    mock_client = MagicMock()
    mock_client.create_merge_request.return_value = "https://gitlab.com/mr/99"
    mock_factory.return_value = mock_client

    response = api_client.post(
        CREATE_MR_ENDPOINT, json=CREATE_MR_REQUEST, headers=auth_headers
    )

    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["url"] == "https://gitlab.com/mr/99"
    mock_client.create_merge_request.assert_called_once()


@patch("qontract_api.external.vcs.router.create_vcs_workspace_client")
def test_create_merge_request_passes_file_operations(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /merge-requests passes file operations correctly."""
    mock_client = MagicMock()
    mock_client.create_merge_request.return_value = "https://gitlab.com/mr/1"
    mock_factory.return_value = mock_client

    api_client.post(CREATE_MR_ENDPOINT, json=CREATE_MR_REQUEST, headers=auth_headers)

    call_args = mock_client.create_merge_request.call_args[0][0]
    assert call_args.title == "[ldap-users] delete user alice"
    assert len(call_args.file_operations) == 1
    assert call_args.file_operations[0].path == "data/users/alice.yml"
    assert call_args.file_operations[0].action.value == "delete"
    assert call_args.auto_merge is True
