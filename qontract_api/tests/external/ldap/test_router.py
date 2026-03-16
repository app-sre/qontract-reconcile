"""Unit tests for LDAP external router endpoints."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

# Query params shared across tests — mirrors LdapSecret fields
LDAP_SECRET_PARAMS = {
    "secret_manager_url": "https://vault.example.com",
    "path": "secret/ldap/client-secret",
    "field": "client_secret",
    "base_url": "https://internal-groups.example.com",
    "token_url": "https://sso.example.com/token",
    "client_id": "ldap-client",
}

LDAP_ENDPOINT = "/api/v1/external/ldap/groups/{group_name}/members"


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    """Create test client with mocked cache and secret_manager in app.state.

    The LDAP endpoint depends on both CacheDep and SecretManagerDep, which are
    resolved from app.state. This fixture sets both mocks so the dependencies
    resolve without a live cache or Vault connection.
    """
    from qontract_api.main import app

    app.state.cache = Mock()
    app.state.secret_manager = Mock()

    yield TestClient(app, raise_server_exceptions=False)

    if hasattr(app.state, "cache"):
        delattr(app.state, "cache")
    if hasattr(app.state, "secret_manager"):
        delattr(app.state, "secret_manager")


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    """Create a mock InternalGroupsWorkspaceClient with two group members."""
    workspace_client = MagicMock()
    member1 = MagicMock()
    member1.id = "user1"
    member2 = MagicMock()
    member2.id = "user2"
    group = MagicMock()
    group.members = [member1, member2]
    workspace_client.get_group.return_value = group
    return workspace_client


@patch("qontract_api.external.ldap.router.create_internal_groups_workspace_client")
def test_get_group_members_returns_members(
    mock_factory: MagicMock,
    api_client: TestClient,
    mock_workspace_client: MagicMock,
) -> None:
    """Test GET /groups/{group_name}/members returns correct member list."""
    mock_factory.return_value = mock_workspace_client

    response = api_client.get(
        LDAP_ENDPOINT.format(group_name="my-ldap-group"),
        params=LDAP_SECRET_PARAMS,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert "members" in data
    assert len(data["members"]) == 2
    member_ids = {m["id"] for m in data["members"]}
    assert member_ids == {"user1", "user2"}

    mock_workspace_client.get_group.assert_called_once_with("my-ldap-group")


@patch("qontract_api.external.ldap.router.create_internal_groups_workspace_client")
def test_get_group_members_requires_cache(
    mock_factory: MagicMock,
    api_client: TestClient,
    mock_workspace_client: MagicMock,
) -> None:
    """Test GET /groups/{group_name}/members works with cache dependency satisfied.

    Verifies that the factory is called with the correct secret parameters
    derived from the query string, confirming end-to-end dependency injection.
    """
    mock_factory.return_value = mock_workspace_client

    response = api_client.get(
        LDAP_ENDPOINT.format(group_name="another-group"),
        params=LDAP_SECRET_PARAMS,
    )

    assert response.status_code == HTTPStatus.OK
    mock_factory.assert_called_once()
    call_kwargs = mock_factory.call_args.kwargs
    assert call_kwargs["secret"].base_url == LDAP_SECRET_PARAMS["base_url"]
    assert call_kwargs["secret"].client_id == LDAP_SECRET_PARAMS["client_id"]
    assert call_kwargs["secret"].token_url == LDAP_SECRET_PARAMS["token_url"]
