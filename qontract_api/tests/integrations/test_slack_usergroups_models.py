"""Unit tests for Slack usergroups models."""

# ruff: noqa: S105, S106
# ruff: noqa: PLR2004 - Magic values acceptable in tests for readability
from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroup,
    SlackUsergroupActionCreate,
    SlackUsergroupActionUpdateMetadata,
    SlackUsergroupActionUpdateUsers,
    SlackUsergroupConfig,
    SlackUsergroupsReconcileRequest,
    SlackUsergroupsTaskResponse,
    SlackUsergroupsTaskResult,
    SlackWorkspace,
)
from qontract_api.models import TaskStatus


def test_slack_usergroup_config_minimal() -> None:
    """Test SlackUsergroupConfig with minimal required fields."""
    config = SlackUsergroupConfig()
    assert not config.description
    assert config.users == frozenset()
    assert config.channels == frozenset()


def test_slack_usergroup_config_full() -> None:
    """Test SlackUsergroupConfig with all fields."""
    config = SlackUsergroupConfig(
        description="Test group description",
        users=["user1@example.com", "user2@example.com"],
        channels=["#general", "#team"],
    )
    assert config.description == "Test group description"
    assert len(config.users) == 2
    assert len(config.channels) == 2


def test_slack_usergroup_model() -> None:
    """Test SlackUsergroup model with handle and config."""
    config = SlackUsergroupConfig(
        description="Test group",
        users=["user1@example.com"],
        channels=["#general"],
    )
    usergroup = SlackUsergroup(handle="test-group", config=config)
    assert usergroup.handle == "test-group"
    assert usergroup.config.description == "Test group"
    assert len(usergroup.config.users) == 1
    assert len(usergroup.config.channels) == 1


def test_slack_workspace_model() -> None:
    """Test SlackWorkspace model with usergroups."""
    config = SlackUsergroupConfig(description="Test group")
    usergroup = SlackUsergroup(handle="test-group", config=config)
    workspace = SlackWorkspace(
        name="test-workspace",
        vault_token_path="app-sre/integrations-output/slack-workspace/token",
        usergroups=frozenset([usergroup]),
        managed_usergroups=["test-group"],
    )
    assert workspace.name == "test-workspace"
    assert (
        workspace.vault_token_path
        == "app-sre/integrations-output/slack-workspace/token"
    )
    assert len(workspace.usergroups) == 1
    assert next(iter(workspace.usergroups)).handle == "test-group"


def test_reconcile_request_dry_run_default_true() -> None:
    """Test that dry_run defaults to True (CRITICAL safety feature)."""
    config = SlackUsergroupConfig()
    usergroup = SlackUsergroup(handle="test-group", config=config)
    workspace = SlackWorkspace(
        name="test-workspace",
        vault_token_path="app-sre/integrations-output/slack-workspace/token",
        usergroups=frozenset([usergroup]),
        managed_usergroups=["test-group"],
    )
    request = SlackUsergroupsReconcileRequest(workspaces=[workspace])
    assert request.dry_run is True  # MUST be True by default!


def test_reconcile_request_dry_run_explicit_false() -> None:
    """Test that dry_run can be explicitly set to False."""
    config = SlackUsergroupConfig()
    usergroup = SlackUsergroup(handle="test-group", config=config)
    workspace = SlackWorkspace(
        name="test-workspace",
        vault_token_path="app-sre/integrations-output/slack-workspace/token",
        usergroups=frozenset([usergroup]),
        managed_usergroups=["test-group"],
    )
    request = SlackUsergroupsReconcileRequest(workspaces=[workspace], dry_run=False)
    assert request.dry_run is False


def test_slack_usergroup_action_create() -> None:
    """Test SlackUsergroupActionCreate model."""
    action = SlackUsergroupActionCreate(
        workspace="test-workspace",
        usergroup="test-group",
        description="Test group description",
    )
    assert action.action_type == "create"
    assert action.workspace == "test-workspace"
    assert action.usergroup == "test-group"
    assert action.description == "Test group description"


def test_slack_usergroup_action_update_users() -> None:
    """Test SlackUsergroupActionUpdateUsers model."""
    action = SlackUsergroupActionUpdateUsers(
        workspace="test-workspace",
        usergroup="test-group",
        users=["user1@example.com", "user2@example.com"],
    )
    assert action.action_type == "update_users"
    assert action.workspace == "test-workspace"
    assert action.usergroup == "test-group"
    assert action.users == ["user1@example.com", "user2@example.com"]


def test_slack_usergroup_action_update_metadata() -> None:
    """Test SlackUsergroupActionUpdateMetadata model."""
    action = SlackUsergroupActionUpdateMetadata(
        workspace="test-workspace",
        usergroup="test-group",
        description="New description",
        channels=["C123", "C456"],
    )
    assert action.action_type == "update_metadata"
    assert action.workspace == "test-workspace"
    assert action.usergroup == "test-group"
    assert action.description == "New description"
    assert action.channels == ["C123", "C456"]


def test_task_result_with_status_pending() -> None:
    """Test SlackUsergroupsTaskResult with pending status."""
    result = SlackUsergroupsTaskResult(
        status=TaskStatus.PENDING,
        actions=[],
        applied_count=0,
        errors=None,
    )
    assert result.status == TaskStatus.PENDING
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors is None


def test_task_result_with_status_success() -> None:
    """Test SlackUsergroupsTaskResult with success status."""
    action = SlackUsergroupActionCreate(
        workspace="test-workspace",
        usergroup="test-group",
        description="Test group description",
    )
    result = SlackUsergroupsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[action],
        applied_count=1,
        errors=None,
    )
    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.applied_count == 1
    assert result.errors is None


def test_task_result_with_status_failed() -> None:
    """Test SlackUsergroupsTaskResult with failed status."""
    result = SlackUsergroupsTaskResult(
        status=TaskStatus.FAILED,
        actions=[],
        applied_count=0,
        errors=["Error 1", "Error 2"],
    )
    assert result.status == TaskStatus.FAILED
    assert len(result.actions) == 0
    assert result.applied_count == 0
    assert result.errors is not None
    assert len(result.errors) == 2


def test_task_response() -> None:
    """Test SlackUsergroupsTaskResponse for POST /reconcile."""
    response = SlackUsergroupsTaskResponse(
        task_id="550e8400-e29b-41d4-a716-446655440000",
        status_url="/api/v1/integrations/slack-usergroups/reconcile/550e8400-e29b-41d4-a716-446655440000",
    )
    assert response.task_id == "550e8400-e29b-41d4-a716-446655440000"
    assert response.status == TaskStatus.PENDING  # Default is PENDING now
    assert "/reconcile/" in response.status_url
