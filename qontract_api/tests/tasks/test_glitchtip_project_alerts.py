"""Unit tests for Glitchtip project alerts Celery task."""

from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.glitchtip_api.models import Organization, Project

from qontract_api.integrations.glitchtip_project_alerts.domain import (
    GlitchtipInstance,
    GlitchtipOrganization,
    GlitchtipProject,
    GlitchtipProjectAlert,
)
from qontract_api.integrations.glitchtip_project_alerts.schemas import (
    GlitchtipAlertActionCreate,
    GlitchtipProjectAlertsTaskResult,
)
from qontract_api.integrations.glitchtip_project_alerts.tasks import (
    generate_lock_key,
    reconcile_glitchtip_project_alerts_task,
)
from qontract_api.models import Secret, TaskStatus


@pytest.fixture
def test_token() -> Secret:
    """Create test secret token."""
    return Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/glitchtip/token",
    )


@pytest.fixture
def sample_instances(test_token: Secret) -> list[GlitchtipInstance]:
    """Create sample instance list."""
    return [
        GlitchtipInstance(
            name="instance-1",
            console_url="https://glitchtip.example.com",
            token=test_token,
            organizations=[
                GlitchtipOrganization(
                    name="my-org",
                    projects=[
                        GlitchtipProject(
                            name="my-project", slug="my-project", alerts=[]
                        )
                    ],
                )
            ],
        )
    ]


def test_generate_lock_key_single_instance(
    sample_instances: list[GlitchtipInstance],
) -> None:
    """Test lock key generation for single instance."""
    mock_self = MagicMock()
    lock_key = generate_lock_key(mock_self, sample_instances)

    assert lock_key == "instance-1"


def test_generate_lock_key_multiple_instances(test_token: Secret) -> None:
    """Test lock key generation for multiple instances (sorted)."""
    instances = [
        GlitchtipInstance(
            name="instance-b",
            console_url="https://glitchtip-b.example.com",
            token=test_token,
            organizations=[],
        ),
        GlitchtipInstance(
            name="instance-a",
            console_url="https://glitchtip-a.example.com",
            token=test_token,
            organizations=[],
        ),
    ]
    mock_self = MagicMock()
    lock_key = generate_lock_key(mock_self, instances)

    # Should be sorted alphabetically
    assert lock_key == "instance-a,instance-b"


@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_secret_manager")
@patch(
    "qontract_api.integrations.glitchtip_project_alerts.tasks.GlitchtipClientFactory"
)
def test_reconcile_task_dry_run_success(
    mock_client_factory_cls: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_event_manager: MagicMock,
    sample_instances: list[GlitchtipInstance],
) -> None:
    """Test task execution in dry-run mode does not publish events."""
    mock_get_cache.return_value = MagicMock()
    mock_get_secret_manager.return_value = MagicMock()
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    mock_workspace_client = MagicMock()
    mock_workspace_client.get_organizations.return_value = {
        "my-org": Organization(pk=1, name="my-org", slug="my-org")
    }
    mock_workspace_client.get_projects.return_value = [
        Project(pk=1, name="my-project", slug="my-project")
    ]
    mock_workspace_client.get_project_alerts.return_value = []
    mock_client_factory_cls.return_value.create_workspace_client.return_value = (
        mock_workspace_client
    )

    mock_self = MagicMock()
    mock_self.request.id = "test-task-123"

    task_func = reconcile_glitchtip_project_alerts_task.__wrapped__.__wrapped__

    result = task_func(mock_self, sample_instances, dry_run=True)

    assert isinstance(result, GlitchtipProjectAlertsTaskResult)
    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 0
    assert result.errors == []
    mock_event_manager.publish_event.assert_not_called()


@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_secret_manager")
@patch(
    "qontract_api.integrations.glitchtip_project_alerts.tasks.GlitchtipClientFactory"
)
def test_reconcile_task_publishes_events_on_non_dry_run(
    mock_client_factory_cls: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_event_manager: MagicMock,
    test_token: Secret,
) -> None:
    """Test that events are published for each applied action in non-dry-run mode."""
    mock_get_cache.return_value = MagicMock()
    mock_get_secret_manager.return_value = MagicMock()
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    mock_workspace_client = MagicMock()
    mock_workspace_client.get_organizations.return_value = {
        "my-org": Organization(pk=1, name="my-org", slug="my-org")
    }
    mock_workspace_client.get_projects.return_value = [
        Project(pk=1, name="my-project", slug="my-project")
    ]
    mock_workspace_client.get_project_alerts.return_value = []
    mock_workspace_client.create_project_alert.return_value = MagicMock(pk=1)
    mock_client_factory_cls.return_value.create_workspace_client.return_value = (
        mock_workspace_client
    )

    instance = GlitchtipInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        organizations=[
            GlitchtipOrganization(
                name="my-org",
                projects=[
                    GlitchtipProject(
                        name="my-project",
                        slug="my-project",
                        alerts=[
                            GlitchtipProjectAlert(
                                name="new-alert",
                                timespan_minutes=5,
                                quantity=100,
                            )
                        ],
                    )
                ],
            )
        ],
    )

    mock_self = MagicMock()
    mock_self.request.id = "test-task-456"

    task_func = reconcile_glitchtip_project_alerts_task.__wrapped__.__wrapped__

    result = task_func(mock_self, [instance], dry_run=False)

    assert isinstance(result, GlitchtipProjectAlertsTaskResult)
    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    assert result.errors == []
    assert len(result.applied_actions) == 1
    assert isinstance(result.applied_actions[0], GlitchtipAlertActionCreate)

    mock_event_manager.publish_event.assert_called_once()
    call_args = mock_event_manager.publish_event.call_args[0][0]
    assert "glitchtip-project-alerts" in call_args.type
    assert (
        call_args.type
        == f"qontract-api.glitchtip-project-alerts.{result.applied_actions[0].action_type}"
    )


@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_secret_manager")
@patch(
    "qontract_api.integrations.glitchtip_project_alerts.tasks.GlitchtipClientFactory"
)
def test_reconcile_task_no_events_when_event_manager_is_none(
    mock_client_factory_cls: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_event_manager: MagicMock,
    test_token: Secret,
) -> None:
    """Test that no error occurs when event_manager is None (events not configured)."""
    mock_get_cache.return_value = MagicMock()
    mock_get_secret_manager.return_value = MagicMock()
    mock_get_event_manager.return_value = None

    mock_workspace_client = MagicMock()
    mock_workspace_client.get_organizations.return_value = {
        "my-org": Organization(pk=1, name="my-org", slug="my-org")
    }
    mock_workspace_client.get_projects.return_value = [
        Project(pk=1, name="my-project", slug="my-project")
    ]
    mock_workspace_client.get_project_alerts.return_value = []
    mock_workspace_client.create_project_alert.return_value = MagicMock(pk=1)
    mock_client_factory_cls.return_value.create_workspace_client.return_value = (
        mock_workspace_client
    )

    instance = GlitchtipInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        organizations=[
            GlitchtipOrganization(
                name="my-org",
                projects=[
                    GlitchtipProject(
                        name="my-project",
                        slug="my-project",
                        alerts=[
                            GlitchtipProjectAlert(
                                name="new-alert",
                                timespan_minutes=5,
                                quantity=100,
                            )
                        ],
                    )
                ],
            )
        ],
    )

    mock_self = MagicMock()
    mock_self.request.id = "test-task-789"

    task_func = reconcile_glitchtip_project_alerts_task.__wrapped__.__wrapped__

    result = task_func(mock_self, [instance], dry_run=False)

    assert isinstance(result, GlitchtipProjectAlertsTaskResult)
    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    assert len(result.applied_actions) == 1


@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_event_manager")
@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_cache")
@patch("qontract_api.integrations.glitchtip_project_alerts.tasks.get_secret_manager")
@patch(
    "qontract_api.integrations.glitchtip_project_alerts.tasks.GlitchtipClientFactory"
)
def test_reconcile_task_publishes_error_events_on_failure(
    mock_client_factory_cls: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
    mock_get_event_manager: MagicMock,
    test_token: Secret,
) -> None:
    """Test that error events are published when actions fail in non-dry-run mode."""
    mock_get_cache.return_value = MagicMock()
    mock_get_secret_manager.return_value = MagicMock()
    mock_event_manager = MagicMock()
    mock_get_event_manager.return_value = mock_event_manager

    mock_workspace_client = MagicMock()
    mock_workspace_client.get_organizations.return_value = {
        "my-org": Organization(pk=1, name="my-org", slug="my-org")
    }
    mock_workspace_client.get_projects.return_value = [
        Project(pk=1, name="my-project", slug="my-project")
    ]
    mock_workspace_client.get_project_alerts.return_value = []
    mock_workspace_client.create_project_alert.side_effect = RuntimeError("API error")
    mock_client_factory_cls.return_value.create_workspace_client.return_value = (
        mock_workspace_client
    )

    instance = GlitchtipInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        organizations=[
            GlitchtipOrganization(
                name="my-org",
                projects=[
                    GlitchtipProject(
                        name="my-project",
                        slug="my-project",
                        alerts=[
                            GlitchtipProjectAlert(
                                name="new-alert",
                                timespan_minutes=5,
                                quantity=100,
                            )
                        ],
                    )
                ],
            )
        ],
    )

    mock_self = MagicMock()
    mock_self.request.id = "test-task-error"

    task_func = reconcile_glitchtip_project_alerts_task.__wrapped__.__wrapped__

    result = task_func(mock_self, [instance], dry_run=False)

    assert isinstance(result, GlitchtipProjectAlertsTaskResult)
    assert result.status == TaskStatus.FAILED
    assert result.applied_count == 0
    assert result.applied_actions == []
    assert len(result.errors) == 1

    # One error event should be published, no success events
    mock_event_manager.publish_event.assert_called_once()
    call_args = mock_event_manager.publish_event.call_args[0][0]
    assert call_args.type == "qontract-api.glitchtip-project-alerts.error"
