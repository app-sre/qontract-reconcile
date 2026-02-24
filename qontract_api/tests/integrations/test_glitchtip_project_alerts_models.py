"""Unit tests for Glitchtip project alerts models."""

from qontract_api.integrations.glitchtip_project_alerts.models import (
    GlitchtipAlertActionCreate,
    GlitchtipAlertActionDelete,
    GlitchtipAlertActionUpdate,
    GlitchtipInstance,
    GlitchtipOrganization,
    GlitchtipProject,
    GlitchtipProjectAlert,
    GlitchtipProjectAlertRecipient,
    GlitchtipProjectAlertsReconcileRequest,
    GlitchtipProjectAlertsTaskResponse,
    GlitchtipProjectAlertsTaskResult,
)
from qontract_api.models import Secret, TaskStatus


def test_glitchtip_project_alert_recipient() -> None:
    """Test GlitchtipProjectAlertRecipient model."""
    recipient = GlitchtipProjectAlertRecipient(
        recipient_type="webhook",
        url="https://example.com/hook",
    )
    assert recipient.recipient_type == "webhook"
    assert recipient.url == "https://example.com/hook"


def test_glitchtip_project_alert_recipient_email() -> None:
    """Test GlitchtipProjectAlertRecipient for email type."""
    recipient = GlitchtipProjectAlertRecipient(
        recipient_type="email",
        url="",
    )
    assert recipient.recipient_type == "email"
    assert not recipient.url


def test_glitchtip_project_alert_minimal() -> None:
    """Test GlitchtipProjectAlert with minimal fields."""
    alert = GlitchtipProjectAlert(
        name="high-error-rate",
        timespan_minutes=5,
        quantity=100,
    )
    assert alert.name == "high-error-rate"
    assert alert.timespan_minutes == 5
    assert alert.quantity == 100
    assert alert.recipients == []


def test_glitchtip_project_alert_with_recipients() -> None:
    """Test GlitchtipProjectAlert with recipients."""
    alert = GlitchtipProjectAlert(
        name="high-error-rate",
        timespan_minutes=1,
        quantity=10,
        recipients=[
            GlitchtipProjectAlertRecipient(recipient_type="email", url=""),
            GlitchtipProjectAlertRecipient(
                recipient_type="webhook", url="https://example.com/hook"
            ),
        ],
    )
    assert len(alert.recipients) == 2


def test_glitchtip_project() -> None:
    """Test GlitchtipProject model."""
    project = GlitchtipProject(
        name="my-project",
        slug="my-project",
        alerts=[GlitchtipProjectAlert(name="alert-1", timespan_minutes=5, quantity=50)],
    )
    assert project.name == "my-project"
    assert project.slug == "my-project"
    assert len(project.alerts) == 1


def test_glitchtip_organization() -> None:
    """Test GlitchtipOrganization model."""
    org = GlitchtipOrganization(
        name="my-org",
        projects=[
            GlitchtipProject(name="project-1", slug="project-1"),
        ],
    )
    assert org.name == "my-org"
    assert len(org.projects) == 1


def test_glitchtip_instance() -> None:
    """Test GlitchtipInstance model."""
    instance = GlitchtipInstance(
        name="my-instance",
        console_url="https://glitchtip.example.com",
        token=Secret(
            secret_manager_url="https://vault.example.com",
            path="secret/glitchtip/token",
        ),
    )
    assert instance.name == "my-instance"
    assert instance.console_url == "https://glitchtip.example.com"
    assert instance.read_timeout == 30
    assert instance.max_retries == 3


def test_glitchtip_reconcile_request() -> None:
    """Test GlitchtipProjectAlertsReconcileRequest model."""
    request = GlitchtipProjectAlertsReconcileRequest(
        instances=[
            GlitchtipInstance(
                name="my-instance",
                console_url="https://glitchtip.example.com",
                token=Secret(
                    secret_manager_url="https://vault.example.com",
                    path="secret/glitchtip/token",
                ),
            )
        ],
        desired_state={
            "my-instance": [GlitchtipOrganization(name="my-org", projects=[])]
        },
        dry_run=True,
    )
    assert len(request.instances) == 1
    assert request.dry_run is True
    assert "my-instance" in request.desired_state


def test_glitchtip_reconcile_request_default_dry_run() -> None:
    """Test that dry_run defaults to True (safety first)."""
    request = GlitchtipProjectAlertsReconcileRequest(
        instances=[],
        desired_state={},
    )
    assert request.dry_run is True


def test_glitchtip_action_create() -> None:
    """Test GlitchtipAlertActionCreate model."""
    action = GlitchtipAlertActionCreate(
        instance="my-instance",
        organization="my-org",
        project="my-project",
        alert_name="high-error-rate",
    )
    assert action.action_type == "create"
    assert action.instance == "my-instance"
    assert action.organization == "my-org"
    assert action.project == "my-project"
    assert action.alert_name == "high-error-rate"


def test_glitchtip_action_update() -> None:
    """Test GlitchtipAlertActionUpdate model."""
    action = GlitchtipAlertActionUpdate(
        instance="my-instance",
        organization="my-org",
        project="my-project",
        alert_name="high-error-rate",
    )
    assert action.action_type == "update"


def test_glitchtip_action_delete() -> None:
    """Test GlitchtipAlertActionDelete model."""
    action = GlitchtipAlertActionDelete(
        instance="my-instance",
        organization="my-org",
        project="my-project",
        alert_name="old-alert",
    )
    assert action.action_type == "delete"


def test_glitchtip_task_result() -> None:
    """Test GlitchtipProjectAlertsTaskResult model."""
    result = GlitchtipProjectAlertsTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            GlitchtipAlertActionCreate(
                instance="inst",
                organization="org",
                project="proj",
                alert_name="alert",
            )
        ],
        applied_count=1,
        errors=[],
    )
    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.applied_count == 1


def test_glitchtip_task_result_defaults() -> None:
    """Test GlitchtipProjectAlertsTaskResult default values."""
    result = GlitchtipProjectAlertsTaskResult(status=TaskStatus.PENDING)
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors == []


def test_glitchtip_task_response() -> None:
    """Test GlitchtipProjectAlertsTaskResponse model."""
    response = GlitchtipProjectAlertsTaskResponse(
        id="task-123",
        status=TaskStatus.PENDING,
        status_url="https://api.example.com/task/task-123",
    )
    assert response.id == "task-123"
    assert response.status == TaskStatus.PENDING
    assert "task-123" in response.status_url
