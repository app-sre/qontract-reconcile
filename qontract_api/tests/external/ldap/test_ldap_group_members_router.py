"""Tests for LDAP group-members resolution router endpoint."""

from collections.abc import Generator
from http import HTTPStatus
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from qontract_api.auth import create_access_token
from qontract_api.exceptions import ValidationError
from qontract_api.external.ldap.schemas import (
    LdapDirectSecret,
    LdapGroupMember,
    LdapGroupMembersRequest,
    LdapGroupResult,
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


LDAP_GROUP_MEMBERS_ENDPOINT = "/api/v1/external/ldap/groups/members"

LDAP_SECRET = LdapDirectSecret(
    secret_manager_url="https://vault.example.com",
    path="secret/ldap/freeipa",
    field="bind_password",
    server_url="ldap://freeipa.example.com",
    base_dn="dc=example,dc=com",
)


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_group_members_returns_resolved_groups(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /groups/members returns resolved membership per group."""
    mock_client = MagicMock()
    mock_client.get_group_members.return_value = [
        LdapGroupResult(
            group="team-a",
            members=[
                LdapGroupMember(
                    name="alice", org_username="alice", github_username="alicegh"
                ),
                LdapGroupMember(name="bob", org_username="bob"),
            ],
        )
    ]
    mock_factory.return_value = mock_client

    response = api_client.post(
        LDAP_GROUP_MEMBERS_ENDPOINT,
        json=LdapGroupMembersRequest(groups=["team-a"], secret=LDAP_SECRET).model_dump(
            mode="json"
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["groups"] == [
        {
            "group": "team-a",
            "members": [
                {
                    "name": "alice",
                    "org_username": "alice",
                    "github_username": "alicegh",
                },
                {"name": "bob", "org_username": "bob", "github_username": None},
            ],
        }
    ]
    mock_client.get_group_members.assert_called_once_with(
        ["team-a"], include_github_usernames=True
    )


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_group_members_omits_unresolved_groups(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """A group that doesn't exist is simply absent from the response."""
    mock_client = MagicMock()
    mock_client.get_group_members.return_value = []
    mock_factory.return_value = mock_client

    response = api_client.post(
        LDAP_GROUP_MEMBERS_ENDPOINT,
        json=LdapGroupMembersRequest(
            groups=["ghost-team"], secret=LDAP_SECRET
        ).model_dump(mode="json"),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["groups"] == []


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_group_members_passes_include_github_usernames_flag(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /groups/members forwards include_github_usernames to the client."""
    mock_client = MagicMock()
    mock_client.get_group_members.return_value = []
    mock_factory.return_value = mock_client

    api_client.post(
        LDAP_GROUP_MEMBERS_ENDPOINT,
        json=LdapGroupMembersRequest(
            groups=["team-a"], secret=LDAP_SECRET, include_github_usernames=False
        ).model_dump(mode="json"),
        headers=auth_headers,
    )

    mock_client.get_group_members.assert_called_once_with(
        ["team-a"], include_github_usernames=False
    )


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_group_members_passes_secret(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Test POST /groups/members passes the Vault secret to the factory."""
    mock_client = MagicMock()
    mock_client.get_group_members.return_value = []
    mock_factory.return_value = mock_client

    api_client.post(
        LDAP_GROUP_MEMBERS_ENDPOINT,
        json=LdapGroupMembersRequest(groups=["team-a"], secret=LDAP_SECRET).model_dump(
            mode="json"
        ),
        headers=auth_headers,
    )

    mock_factory.assert_called_once()
    call_kwargs = mock_factory.call_args.kwargs
    assert call_kwargs["secret"].server_url == "ldap://freeipa.example.com"
    assert call_kwargs["secret"].base_dn == "dc=example,dc=com"


@patch("qontract_api.external.ldap.router.create_ldap_workspace_client")
def test_group_members_oversized_group_returns_422(
    mock_factory: MagicMock,
    api_client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Fail-closed: an oversized group surfaces as a 422, not a truncated 200."""
    mock_client = MagicMock()
    mock_client.get_group_members.side_effect = ValidationError(
        "LDAP group 'big-team' has 501 members, exceeding the configured "
        "max_group_size of 500"
    )
    mock_factory.return_value = mock_client

    response = api_client.post(
        LDAP_GROUP_MEMBERS_ENDPOINT,
        json=LdapGroupMembersRequest(
            groups=["big-team"], secret=LDAP_SECRET
        ).model_dump(mode="json"),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "big-team" in response.json()["message"]
