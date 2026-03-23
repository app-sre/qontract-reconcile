"""Unit tests for GithubOwnersService."""

from unittest.mock import MagicMock

import pytest

from qontract_api.config import Settings
from qontract_api.github import GithubOrgWorkspaceClient
from qontract_api.integrations.github_owners.domain import GithubOrgDesiredState
from qontract_api.integrations.github_owners.schemas import GithubOwnerActionAddOwner
from qontract_api.integrations.github_owners.service import GithubOwnersService
from qontract_api.models import Secret, TaskStatus


@pytest.fixture
def mock_settings() -> Settings:
    from qontract_api.config import SecretSettings, VaultSettings

    return Settings(
        secrets=SecretSettings(
            providers=[VaultSettings(url="https://vault.example.com")],
            default_provider_url="https://vault.example.com",
        ),
    )


@pytest.fixture
def test_token() -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/github/token",
    )


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    mock = MagicMock()
    mock.read.return_value = "gh-token-abc123"
    return mock


@pytest.fixture
def mock_github_client() -> MagicMock:
    mock = MagicMock(spec=GithubOrgWorkspaceClient)
    mock.get_current_members.return_value = ["alice", "bob"]
    return mock


@pytest.fixture
def mock_github_client_factory(mock_github_client: MagicMock) -> MagicMock:
    mock = MagicMock()
    mock.create_workspace_client.return_value = mock_github_client
    return mock


@pytest.fixture
def service(
    mock_github_client_factory: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> GithubOwnersService:
    return GithubOwnersService(
        github_org_client_factory=mock_github_client_factory,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )


@pytest.fixture
def test_org(test_token: Secret) -> GithubOrgDesiredState:
    return GithubOrgDesiredState(
        org_name="my-org",
        token=test_token,
        owners=["alice", "bob"],
    )


def test_reconcile_no_changes(
    service: GithubOwnersService,
    test_org: GithubOrgDesiredState,
) -> None:
    """No actions generated when desired == current."""
    result = service.reconcile(organizations=[test_org], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors == []


def test_reconcile_adds_missing_owner(
    service: GithubOwnersService,
    test_token: Secret,
    mock_github_client: MagicMock,
) -> None:
    """add_owner action generated for user in desired but not current."""
    mock_github_client.get_current_members.return_value = ["alice"]

    org = GithubOrgDesiredState(
        org_name="my-org",
        token=test_token,
        owners=["alice", "charlie"],
    )

    result = service.reconcile(organizations=[org], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GithubOwnerActionAddOwner)
    assert result.actions[0].username == "charlie"
    assert result.actions[0].org_name == "my-org"
    assert result.applied_count == 0  # dry_run=True


def test_reconcile_does_not_remove_extra_owners(
    service: GithubOwnersService,
    test_org: GithubOrgDesiredState,
    mock_github_client: MagicMock,
) -> None:
    """No remove actions generated — owner removal is intentionally not supported."""
    mock_github_client.get_current_members.return_value = ["alice", "bob", "eve"]

    result = service.reconcile(organizations=[test_org], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []


def test_reconcile_applies_action_when_not_dry_run(
    service: GithubOwnersService,
    test_token: Secret,
    mock_github_client: MagicMock,
) -> None:
    """add_member_as_admin called when dry_run=False."""
    mock_github_client.get_current_members.return_value = ["alice"]

    org = GithubOrgDesiredState(
        org_name="my-org",
        token=test_token,
        owners=["alice", "charlie"],
    )

    result = service.reconcile(organizations=[org], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    mock_github_client.add_member_as_admin.assert_called_once_with("my-org", "charlie")


def test_reconcile_handles_org_error(
    service: GithubOwnersService,
    test_org: GithubOrgDesiredState,
    mock_github_client_factory: MagicMock,
) -> None:
    """Errors per org are collected; reconcile continues to other orgs."""
    mock_github_client_factory.create_workspace_client.side_effect = RuntimeError(
        "Connection failed"
    )

    result = service.reconcile(organizations=[test_org], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "Connection failed" in result.errors[0]
    assert "my-org" in result.errors[0]


def test_reconcile_handles_action_execution_error(
    service: GithubOwnersService,
    test_token: Secret,
    mock_github_client: MagicMock,
) -> None:
    """Errors during action execution are collected; other actions continue."""
    mock_github_client.get_current_members.return_value = []
    mock_github_client.add_member_as_admin.side_effect = RuntimeError("API error")

    org = GithubOrgDesiredState(
        org_name="my-org",
        token=test_token,
        owners=["alice"],
    )

    result = service.reconcile(organizations=[org], dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "alice" in result.errors[0]


def test_reconcile_multiple_orgs(
    service: GithubOwnersService,
    test_token: Secret,
    mock_github_client: MagicMock,
) -> None:
    """Actions calculated for each org independently."""
    mock_github_client.get_current_members.return_value = []

    orgs = [
        GithubOrgDesiredState(org_name="org-a", token=test_token, owners=["alice"]),
        GithubOrgDesiredState(org_name="org-b", token=test_token, owners=["bob"]),
    ]

    result = service.reconcile(organizations=orgs, dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 2
    org_names = {a.org_name for a in result.actions}
    assert org_names == {"org-a", "org-b"}


def test_owners_are_normalized(test_token: Secret) -> None:
    """GithubOrgDesiredState normalizes owners to lowercase sorted."""
    org = GithubOrgDesiredState(
        org_name="my-org",
        token=test_token,
        owners=["Charlie", "alice", "BOB"],
    )

    assert org.owners == ["alice", "bob", "charlie"]
