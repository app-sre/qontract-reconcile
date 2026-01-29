"""Unit tests for SlackUsergroupsService."""


# ruff: noqa: ARG001 - Unused fixtures acceptable for test setup

from unittest.mock import MagicMock

import pytest

from qontract_api.config import Settings
from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroup,
    SlackUsergroupActionCreate,
    SlackUsergroupActionUpdateMetadata,
    SlackUsergroupActionUpdateUsers,
    SlackUsergroupConfig,
    SlackWorkspace,
)
from qontract_api.integrations.slack_usergroups.service import SlackUsergroupsService
from qontract_api.integrations.slack_usergroups.slack_workspace_client import (
    SlackWorkspaceClient,
)
from qontract_api.models import Secret, TaskStatus


@pytest.fixture
def mock_settings() -> Settings:
    """Create Settings with test values."""
    from qontract_api.config import (
        SecretSettings,
        VaultSettings,
    )

    return Settings(
        secrets=SecretSettings(
            providers=[
                VaultSettings(
                    url="https://vault.example.com",
                )
            ],
            default_provider_url="https://vault.example.com",
        ),
    )


@pytest.fixture
def test_token() -> Secret:
    """Create test secret token."""
    return Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/slack/test-workspace",
    )


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    """Mock SecretBackend for testing."""

    def _read_secret(secret: Secret) -> str:
        # Return a token based on the path
        return f"xoxb-token-for-{secret.path}"

    mock = MagicMock()
    mock.read.side_effect = _read_secret
    return mock


@pytest.fixture
def mock_slack_client() -> MagicMock:
    """Create mock SlackWorkspaceClient."""
    mock = MagicMock(spec=SlackWorkspaceClient)
    mock.get_slack_usergroups.return_value = []
    mock.clean_slack_usergroups.return_value = []
    return mock


@pytest.fixture
def mock_slack_client_factory(mock_slack_client: MagicMock) -> MagicMock:
    """Mock SlackClientFactory."""
    mock = MagicMock()
    mock.create_workspace_client.return_value = mock_slack_client
    return mock


@pytest.fixture
def service(
    mock_slack_client_factory: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> SlackUsergroupsService:
    """Create SlackUsergroupsService with mocks."""
    return SlackUsergroupsService(
        slack_client_factory=mock_slack_client_factory,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )


# Initialization


def test_service_initialization(service: SlackUsergroupsService) -> None:
    """Test service initializes with all dependencies."""
    assert service.slack_client_factory is not None
    assert service.secret_manager is not None
    assert service.settings is not None


# Empty state (no actions)


def test_reconcile_empty_workspaces_dry_run(service: SlackUsergroupsService) -> None:
    """Test reconcile with no workspaces returns empty result."""
    result = service.reconcile(workspaces=[], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors == []


def test_reconcile_no_usergroups_dry_run(
    service: SlackUsergroupsService, mock_slack_client: MagicMock, test_token: Secret
) -> None:
    """Test reconcile with workspace but no usergroups."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[],
        token=test_token,
    )

    # Mock: current state = empty, desired state = empty
    mock_slack_client.get_slack_usergroups.return_value = []
    mock_slack_client.clean_slack_usergroups.return_value = []

    result = service.reconcile(workspaces=[workspace], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors == []


# Create action


def test_reconcile_create_usergroup_dry_run(
    service: SlackUsergroupsService, mock_slack_client: MagicMock, test_token: Secret
) -> None:
    """Test reconcile generates create action for new usergroup (dry-run)."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[
            SlackUsergroup(
                handle="oncall",
                config=SlackUsergroupConfig(
                    users=["alice", "bob"],
                    channels=["general"],
                    description="On-call team",
                ),
            )
        ],
        token=test_token,
    )

    # Mock: current state = empty (usergroup doesn't exist)
    mock_slack_client.get_slack_usergroups.return_value = []
    # Mock: desired state = usergroup should exist
    mock_slack_client.clean_slack_usergroups.return_value = workspace.usergroups

    result = service.reconcile(workspaces=[workspace], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SlackUsergroupActionCreate)
    assert result.actions[0].workspace == "test-workspace"
    assert result.actions[0].usergroup == "oncall"
    assert result.actions[0].users == ["alice", "bob"]
    assert result.actions[0].description == "On-call team"
    assert result.applied_count == 0  # dry-run
    assert result.errors == []


def test_reconcile_create_usergroup_apply(
    service: SlackUsergroupsService, mock_slack_client: MagicMock, test_token: Secret
) -> None:
    """Test reconcile creates usergroup (apply mode)."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[
            SlackUsergroup(
                handle="oncall",
                config=SlackUsergroupConfig(
                    users=["alice"],
                    channels=[],
                    description="",
                ),
            )
        ],
        token=test_token,
    )

    # Mock: current state = empty
    mock_slack_client.get_slack_usergroups.return_value = []
    # Mock: desired state = usergroup should exist
    mock_slack_client.clean_slack_usergroups.return_value = workspace.usergroups

    result = service.reconcile(workspaces=[workspace], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SlackUsergroupActionCreate)
    assert result.applied_count == 1  # applied!
    mock_slack_client.create_usergroup.assert_called_once_with(handle="oncall")
    assert result.errors == []


# Update users action


def test_reconcile_update_users_dry_run(
    service: SlackUsergroupsService, mock_slack_client: MagicMock, test_token: Secret
) -> None:
    """Test reconcile generates update users action (dry-run)."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[
            SlackUsergroup(
                handle="oncall",
                config=SlackUsergroupConfig(
                    users=["alice", "bob", "charlie"],
                    channels=[],
                    description="",
                ),
            )
        ],
        token=test_token,
    )

    # Mock: current state = usergroup exists with different users
    current_usergroup = SlackUsergroup(
        handle="oncall",
        config=SlackUsergroupConfig(
            users=["alice", "bob"],  # Missing charlie
            channels=[],
            description="",
        ),
    )
    mock_slack_client.get_slack_usergroups.return_value = [current_usergroup]
    # Mock: desired state = usergroup with updated users
    mock_slack_client.clean_slack_usergroups.return_value = workspace.usergroups

    result = service.reconcile(workspaces=[workspace], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SlackUsergroupActionUpdateUsers)
    assert result.actions[0].workspace == "test-workspace"
    assert result.actions[0].usergroup == "oncall"
    assert result.actions[0].users == ["alice", "bob", "charlie"]
    assert "charlie" in result.actions[0].users_to_add
    assert result.actions[0].users_to_remove == []
    assert result.applied_count == 0  # dry-run
    assert result.errors == []


def test_reconcile_update_users_apply(
    service: SlackUsergroupsService, mock_slack_client: MagicMock, test_token: Secret
) -> None:
    """Test reconcile updates usergroup users (apply mode)."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[
            SlackUsergroup(
                handle="oncall",
                config=SlackUsergroupConfig(
                    users=["alice"],
                    channels=[],
                    description="",
                ),
            )
        ],
        token=test_token,
    )

    # Mock: current state = usergroup with old users
    current_usergroup = SlackUsergroup(
        handle="oncall",
        config=SlackUsergroupConfig(
            users=["bob"],
            channels=[],
            description="",
        ),
    )
    mock_slack_client.get_slack_usergroups.return_value = [current_usergroup]
    # Mock: desired state = usergroup with new users
    mock_slack_client.clean_slack_usergroups.return_value = workspace.usergroups

    result = service.reconcile(workspaces=[workspace], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.applied_count == 1
    mock_slack_client.update_usergroup_users.assert_called_once_with(
        handle="oncall", users=["alice"]
    )
    assert result.errors == []


# Update metadata action


def test_reconcile_update_metadata_dry_run(
    service: SlackUsergroupsService, mock_slack_client: MagicMock, test_token: Secret
) -> None:
    """Test reconcile generates update metadata action (dry-run)."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[
            SlackUsergroup(
                handle="oncall",
                config=SlackUsergroupConfig(
                    users=["alice"],
                    channels=["general", "alerts"],
                    description="Updated description",
                ),
            )
        ],
        token=test_token,
    )

    # Mock: current state = usergroup with old metadata
    current_usergroup = SlackUsergroup(
        handle="oncall",
        config=SlackUsergroupConfig(
            users=["alice"],
            channels=["general"],  # Missing alerts
            description="Old description",
        ),
    )
    mock_slack_client.get_slack_usergroups.return_value = [current_usergroup]
    # Mock: desired state = usergroup with updated metadata
    mock_slack_client.clean_slack_usergroups.return_value = workspace.usergroups

    result = service.reconcile(workspaces=[workspace], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], SlackUsergroupActionUpdateMetadata)
    assert result.actions[0].workspace == "test-workspace"
    assert result.actions[0].usergroup == "oncall"
    assert sorted(result.actions[0].channels) == ["alerts", "general"]
    assert result.actions[0].description == "Updated description"
    assert result.applied_count == 0  # dry-run
    assert result.errors == []


# Multiple actions


def test_reconcile_multiple_actions_dry_run(
    service: SlackUsergroupsService, mock_slack_client: MagicMock, test_token: Secret
) -> None:
    """Test reconcile generates multiple actions for different changes."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[
            SlackUsergroup(
                handle="oncall",
                config=SlackUsergroupConfig(
                    users=["alice", "bob"],
                    channels=["alerts"],
                    description="New description",
                ),
            )
        ],
        token=test_token,
    )

    # Mock: current state = usergroup with different users AND metadata
    current_usergroup = SlackUsergroup(
        handle="oncall",
        config=SlackUsergroupConfig(
            users=["alice"],  # Missing bob
            channels=[],  # Missing alerts
            description="Old",  # Different
        ),
    )
    mock_slack_client.get_slack_usergroups.return_value = [current_usergroup]
    # Mock: desired state
    mock_slack_client.clean_slack_usergroups.return_value = workspace.usergroups

    result = service.reconcile(workspaces=[workspace], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 2  # Update users + Update metadata
    assert any(isinstance(a, SlackUsergroupActionUpdateUsers) for a in result.actions)
    assert any(
        isinstance(a, SlackUsergroupActionUpdateMetadata) for a in result.actions
    )
    assert result.applied_count == 0  # dry-run
    assert result.errors == []


# Error handling


def test_reconcile_error_in_workspace_processing(
    service: SlackUsergroupsService,
    mock_slack_client: MagicMock,
    mock_secret_manager: MagicMock,
    test_token: Secret,
) -> None:
    """Test reconcile handles errors in workspace processing."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[],
        token=test_token,
    )

    # Mock: mock_secret_manager raises exception
    mock_secret_manager.read.side_effect = Exception("Secret read error")

    result = service.reconcile(workspaces=[workspace], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors is not None
    assert len(result.errors) == 1
    assert "test-workspace" in result.errors[0]
    assert "Secret read error" in result.errors[0]


def test_reconcile_error_in_action_execution(
    service: SlackUsergroupsService, mock_slack_client: MagicMock, test_token: Secret
) -> None:
    """Test reconcile handles errors during action execution (apply mode)."""
    workspace = SlackWorkspace(
        name="test-workspace",
        managed_usergroups=["oncall"],
        usergroups=[
            SlackUsergroup(
                handle="oncall",
                config=SlackUsergroupConfig(
                    users=["alice"], channels=[], description=""
                ),
            )
        ],
        token=test_token,
    )

    # Mock: current state = empty (will create usergroup)
    mock_slack_client.get_slack_usergroups.return_value = []
    mock_slack_client.clean_slack_usergroups.return_value = workspace.usergroups
    # Mock: create_usergroup raises exception
    mock_slack_client.create_usergroup.side_effect = Exception("Slack API error")

    result = service.reconcile(workspaces=[workspace], dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert len(result.actions) == 1  # Action was generated
    assert result.applied_count == 0  # But not applied due to error
    assert result.errors is not None
    assert len(result.errors) == 1
    assert "Slack API error" in result.errors[0]


# Dependency Injection


def test_create_slack_client_uses_factory(
    service: SlackUsergroupsService,
    mock_slack_client_factory: MagicMock,
    mock_secret_manager: MagicMock,
    test_token: Secret,
) -> None:
    """Test _create_slack_client uses factory and secret reader."""
    client = service._create_slack_client(
        workspace_name="test-workspace", token=test_token
    )

    # Verify secret was read with correct Secret object
    mock_secret_manager.read.assert_called_once()
    call_args = mock_secret_manager.read.call_args[0][0]
    assert isinstance(call_args, Secret)
    assert call_args.path == "secret/slack/test-workspace"

    # Verify factory was called with workspace name and token
    mock_slack_client_factory.create_workspace_client.assert_called_once_with(
        workspace_name="test-workspace",
        token="xoxb-token-for-secret/slack/test-workspace",
    )

    assert client is not None


# _calculate_update_actions static method


def test_calculate_update_actions_no_changes() -> None:
    """Test _calculate_update_actions returns empty list when states match."""
    current = [
        SlackUsergroup(
            handle="oncall",
            config=SlackUsergroupConfig(users=["alice"], channels=[], description=""),
        )
    ]
    desired = [
        SlackUsergroup(
            handle="oncall",
            config=SlackUsergroupConfig(users=["alice"], channels=[], description=""),
        )
    ]

    actions = SlackUsergroupsService._calculate_update_actions(
        workspace="test", current_state=current, desired_state=desired
    )

    assert actions == []


def test_calculate_update_actions_create() -> None:
    """Test _calculate_update_actions generates create action."""
    current: list[SlackUsergroup] = []
    desired = [
        SlackUsergroup(
            handle="oncall",
            config=SlackUsergroupConfig(
                users=["alice"], channels=["general"], description="Team"
            ),
        )
    ]

    actions = SlackUsergroupsService._calculate_update_actions(
        workspace="test", current_state=current, desired_state=desired
    )

    assert len(actions) == 1
    assert isinstance(actions[0], SlackUsergroupActionCreate)
    assert actions[0].usergroup == "oncall"


def test_calculate_update_actions_update_users() -> None:
    """Test _calculate_update_actions generates update users action."""
    current = [
        SlackUsergroup(
            handle="oncall",
            config=SlackUsergroupConfig(users=["alice"], channels=[], description=""),
        )
    ]
    desired = [
        SlackUsergroup(
            handle="oncall",
            config=SlackUsergroupConfig(
                users=["alice", "bob"], channels=[], description=""
            ),
        )
    ]

    actions = SlackUsergroupsService._calculate_update_actions(
        workspace="test", current_state=current, desired_state=desired
    )

    assert len(actions) == 1
    assert isinstance(actions[0], SlackUsergroupActionUpdateUsers)
    assert actions[0].users == ["alice", "bob"]
    assert "bob" in actions[0].users_to_add


def test_calculate_update_actions_update_metadata() -> None:
    """Test _calculate_update_actions generates update metadata action."""
    current = [
        SlackUsergroup(
            handle="oncall",
            config=SlackUsergroupConfig(
                users=["alice"], channels=[], description="Old"
            ),
        )
    ]
    desired = [
        SlackUsergroup(
            handle="oncall",
            config=SlackUsergroupConfig(
                users=["alice"], channels=["general"], description="New"
            ),
        )
    ]

    actions = SlackUsergroupsService._calculate_update_actions(
        workspace="test", current_state=current, desired_state=desired
    )

    assert len(actions) == 1
    assert isinstance(actions[0], SlackUsergroupActionUpdateMetadata)
    assert actions[0].description == "New"
    assert sorted(actions[0].channels) == ["general"]
