"""Unit tests for Slack usergroups Celery task."""

from unittest.mock import MagicMock, patch

import pytest

from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroup,
    SlackUsergroupConfig,
    SlackUsergroupsTaskResult,
    SlackWorkspace,
)
from qontract_api.integrations.slack_usergroups.tasks import (
    generate_lock_key,
    reconcile_slack_usergroups_task,
)
from qontract_api.models import TaskStatus


@pytest.fixture
def sample_workspaces() -> list[SlackWorkspace]:
    """Create sample workspace list."""
    return [
        SlackWorkspace(
            name="workspace-1",
            managed_usergroups=["oncall"],
            usergroups=[
                SlackUsergroup(
                    handle="oncall",
                    config=SlackUsergroupConfig(
                        users=["alice@example.com"],
                        channels=[],
                        description="",
                    ),
                )
            ],
        )
    ]


def test_generate_lock_key_single_workspace(
    sample_workspaces: list[SlackWorkspace],
) -> None:
    """Test lock key generation for single workspace."""
    mock_self = MagicMock()
    lock_key = generate_lock_key(mock_self, sample_workspaces)

    assert lock_key == "workspace-1"


def test_generate_lock_key_multiple_workspaces() -> None:
    """Test lock key generation for multiple workspaces (sorted)."""
    workspaces = [
        SlackWorkspace(
            name="workspace-b",
            managed_usergroups=[],
            usergroups=[],
        ),
        SlackWorkspace(
            name="workspace-a",
            managed_usergroups=[],
            usergroups=[],
        ),
    ]
    mock_self = MagicMock()
    lock_key = generate_lock_key(mock_self, workspaces)

    # Should be sorted alphabetically
    assert lock_key == "workspace-a,workspace-b"


@patch("qontract_api.integrations.slack_usergroups.tasks.settings")
@patch("qontract_api.integrations.slack_usergroups.tasks.get_cache")
@patch("qontract_api.integrations.slack_usergroups.tasks.get_secret_manager")
@patch("qontract_api.integrations.slack_usergroups.tasks.SlackClientFactory")
def test_reconcile_task_dry_run_success(
    mock_factory_class: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
    mock_settings: MagicMock,
    sample_workspaces: list[SlackWorkspace],
) -> None:
    """Test task execution in dry-run mode."""
    from qontract_api.config import (
        Secret,
        Settings,
        SlackIntegrationsSettings,
        SlackWorkspaceSettings,
    )

    # Setup settings mock
    settings_instance = Settings()
    settings_instance.slack.workspaces["workspace-1"] = SlackWorkspaceSettings(
        integrations={
            "slack-usergroups": SlackIntegrationsSettings(
                token=Secret(path="slack/workspace-1/token")
            )
        }
    )
    mock_settings.slack = settings_instance.slack

    # Setup mocks
    mock_cache = MagicMock()
    mock_get_cache.return_value = mock_cache

    mock_secret_backend = MagicMock()
    mock_secret_backend.read.return_value = "xoxb-test-token"
    mock_get_secret_manager.return_value = mock_secret_backend

    mock_slack_client = MagicMock()
    mock_slack_client.get_slack_usergroups.return_value = []
    mock_slack_client.clean_slack_usergroups.return_value = []

    mock_factory = MagicMock()
    mock_factory.create_workspace_client.return_value = mock_slack_client
    mock_factory_class.return_value = mock_factory

    # Create mock task instance
    mock_self = MagicMock()
    mock_self.request.id = "test-task-123"

    # Access the underlying function bypassing the decorator
    task_func = reconcile_slack_usergroups_task.__wrapped__.__wrapped__

    # Execute task (dry-run)
    result = task_func(mock_self, sample_workspaces, dry_run=True)

    # Verify result
    assert isinstance(result, SlackUsergroupsTaskResult)
    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 0  # dry-run
    assert result.errors is None

    # Verify secret was read
    assert mock_secret_backend.read.called
