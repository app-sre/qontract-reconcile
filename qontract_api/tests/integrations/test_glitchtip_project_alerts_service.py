"""Unit tests for GlitchtipProjectAlertsService."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.glitchtip_api.models import Organization, Project, ProjectAlert

from qontract_api.config import Settings
from qontract_api.integrations.glitchtip_project_alerts.glitchtip_workspace_client import (
    GlitchtipWorkspaceClient,
)
from qontract_api.integrations.glitchtip_project_alerts.models import (
    GlitchtipAlertActionCreate,
    GlitchtipAlertActionDelete,
    GlitchtipAlertActionUpdate,
    GlitchtipInstance,
    GlitchtipOrganization,
    GlitchtipProject,
    GlitchtipProjectAlert,
)
from qontract_api.integrations.glitchtip_project_alerts.service import (
    GlitchtipProjectAlertsService,
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
        path="secret/glitchtip/token",
    )


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    """Mock SecretManager for testing."""

    def _read_secret(secret: Secret) -> str:
        return f"glitchtip-token-for-{secret.path}"

    mock = MagicMock()
    mock.read.side_effect = _read_secret
    return mock


@pytest.fixture
def mock_glitchtip_client() -> MagicMock:
    """Create mock GlitchtipWorkspaceClient."""
    mock = MagicMock(spec=GlitchtipWorkspaceClient)
    mock.get_organizations.return_value = {
        "my-org": Organization(pk=1, name="my-org", slug="my-org")
    }
    mock.get_projects.return_value = [
        Project(pk=1, name="my-project", slug="my-project")
    ]
    mock.get_project_alerts.return_value = []
    return mock


@pytest.fixture
def mock_glitchtip_client_factory(mock_glitchtip_client: MagicMock) -> MagicMock:
    """Mock GlitchtipClientFactory."""
    mock = MagicMock()
    mock.create_workspace_client.return_value = mock_glitchtip_client
    return mock


@pytest.fixture
def service(
    mock_glitchtip_client_factory: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> GlitchtipProjectAlertsService:
    """Create GlitchtipProjectAlertsService with mocked dependencies."""
    return GlitchtipProjectAlertsService(
        glitchtip_client_factory=mock_glitchtip_client_factory,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )


@pytest.fixture
def test_instance(test_token: Secret) -> GlitchtipInstance:
    """Create test GlitchtipInstance."""
    return GlitchtipInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        organizations=[
            GlitchtipOrganization(
                name="my-org",
                projects=[
                    GlitchtipProject(name="my-project", slug="my-project", alerts=[])
                ],
            )
        ],
    )


def test_reconcile_no_changes(
    service: GlitchtipProjectAlertsService,
    test_instance: GlitchtipInstance,
) -> None:
    """Test reconcile with no changes needed."""
    result = service.reconcile(
        instances=[test_instance],
        dry_run=True,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors == []


def test_reconcile_creates_new_alert(
    service: GlitchtipProjectAlertsService,
    test_token: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates create action when alert is in desired but not current."""
    mock_glitchtip_client.get_project_alerts.return_value = []

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

    result = service.reconcile(
        instances=[instance],
        dry_run=True,
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipAlertActionCreate)
    assert result.actions[0].alert_name == "new-alert"
    assert result.applied_count == 0  # dry_run=True


def test_reconcile_deletes_removed_alert(
    service: GlitchtipProjectAlertsService,
    test_instance: GlitchtipInstance,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates delete action when alert is in current but not desired."""
    mock_glitchtip_client.get_project_alerts.return_value = [
        ProjectAlert(pk=42, name="old-alert", timespan_minutes=5, quantity=50)
    ]

    result = service.reconcile(
        instances=[test_instance],
        dry_run=True,
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipAlertActionDelete)
    assert result.actions[0].alert_name == "old-alert"


def test_reconcile_updates_changed_alert(
    service: GlitchtipProjectAlertsService,
    test_token: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates update action when alert configuration differs."""
    mock_glitchtip_client.get_project_alerts.return_value = [
        ProjectAlert(pk=10, name="my-alert", timespan_minutes=5, quantity=50)
    ]

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
                                name="my-alert",
                                timespan_minutes=5,
                                quantity=100,  # Changed
                            )
                        ],
                    )
                ],
            )
        ],
    )

    result = service.reconcile(
        instances=[instance],
        dry_run=True,
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipAlertActionUpdate)
    assert result.actions[0].alert_name == "my-alert"


def test_reconcile_skips_unknown_organization(
    service: GlitchtipProjectAlertsService,
    test_token: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile skips organizations that don't exist in current state."""
    mock_glitchtip_client.get_organizations.return_value = {}

    instance = GlitchtipInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        organizations=[
            GlitchtipOrganization(
                name="nonexistent-org",
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

    result = service.reconcile(
        instances=[instance],
        dry_run=True,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []


def test_reconcile_handles_instance_error(
    service: GlitchtipProjectAlertsService,
    test_instance: GlitchtipInstance,
    mock_glitchtip_client_factory: MagicMock,
) -> None:
    """Test reconcile handles errors per instance and continues."""
    mock_glitchtip_client_factory.create_workspace_client.side_effect = RuntimeError(
        "Connection failed"
    )

    result = service.reconcile(
        instances=[test_instance],
        dry_run=True,
    )

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "Connection failed" in result.errors[0]


def test_reconcile_applies_actions_when_not_dry_run(
    service: GlitchtipProjectAlertsService,
    test_token: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile actually creates alerts when dry_run=False."""
    mock_glitchtip_client.get_project_alerts.return_value = []
    mock_glitchtip_client.create_project_alert.return_value = ProjectAlert(
        pk=1, name="new-alert", timespan_minutes=5, quantity=100
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

    result = service.reconcile(
        instances=[instance],
        dry_run=False,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    mock_glitchtip_client.create_project_alert.assert_called_once()
