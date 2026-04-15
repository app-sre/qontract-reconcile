"""Unit tests for GlitchtipService."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.glitchtip_api.models import Organization, Project, Team, User

from qontract_api.config import Settings
from qontract_api.glitchtip import GlitchtipWorkspaceClient
from qontract_api.integrations.glitchtip.domain import (
    GIInstance,
    GIOrganization,
    GIProject,
    GlitchtipTeam,
    GlitchtipUser,
)
from qontract_api.integrations.glitchtip.schemas import (
    GlitchtipActionAddUserToTeam,
    GlitchtipActionCreateOrganization,
    GlitchtipActionCreateProject,
    GlitchtipActionCreateTeam,
    GlitchtipActionDeleteOrganization,
    GlitchtipActionDeleteProject,
    GlitchtipActionDeleteTeam,
    GlitchtipActionDeleteUser,
    GlitchtipActionInviteUser,
    GlitchtipActionRemoveProjectFromTeam,
    GlitchtipActionRemoveUserFromTeam,
    GlitchtipActionUpdateProject,
    GlitchtipActionUpdateUserRole,
)
from qontract_api.integrations.glitchtip.service import GlitchtipService
from qontract_api.models import Secret, TaskStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings() -> Settings:
    """Create Settings with test values."""
    from qontract_api.config import SecretSettings, VaultSettings

    return Settings(
        secrets=SecretSettings(
            providers=[VaultSettings(url="https://vault.example.com")],
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
def test_automation_email_secret() -> Secret:
    """Create test secret for automation user email."""
    return Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/glitchtip/automation-email",
    )


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    """Mock SecretManager that returns 'test-value' for all secrets."""
    mock = MagicMock()
    mock.read.return_value = "test-value"
    return mock


@pytest.fixture
def mock_glitchtip_client() -> MagicMock:
    """Create a mock GlitchtipWorkspaceClient with sensible defaults.

    Defaults: org 'my-org' exists, no users, no teams, no projects.
    """
    mock = MagicMock(spec=GlitchtipWorkspaceClient)
    mock.get_organizations.return_value = {
        "my-org": Organization(pk=1, name="my-org", slug="my-org")
    }
    mock.get_organization_users.return_value = []
    mock.get_teams.return_value = []
    mock.get_projects.return_value = []
    mock.get_team_users.return_value = []
    return mock


@pytest.fixture
def mock_glitchtip_client_factory(mock_glitchtip_client: MagicMock) -> MagicMock:
    """Mock GlitchtipClientFactory that returns mock_glitchtip_client."""
    mock = MagicMock()
    mock.create_workspace_client.return_value = mock_glitchtip_client
    return mock


@pytest.fixture
def service(
    mock_glitchtip_client_factory: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> GlitchtipService:
    """Create GlitchtipService with mocked dependencies."""
    return GlitchtipService(
        glitchtip_client_factory=mock_glitchtip_client_factory,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )


@pytest.fixture
def test_instance(
    test_token: Secret,
    test_automation_email_secret: Secret,
) -> GIInstance:
    """Create a test GIInstance with a single desired organization."""
    return GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[GIOrganization(name="my-org", teams=[], projects=[], users=[])],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reconcile_no_changes(
    service: GlitchtipService,
    test_instance: GIInstance,
) -> None:
    """Test reconcile with matching desired and current state produces no actions."""
    result = service.reconcile(instances=[test_instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors == []


def test_reconcile_creates_organization(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates create_organization when desired org is missing from current."""
    mock_glitchtip_client.get_organizations.return_value = {}

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[GIOrganization(name="new-org", teams=[], projects=[], users=[])],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipActionCreateOrganization)
    assert result.actions[0].organization == "new-org"
    assert result.applied_count == 0


def test_reconcile_deletes_organization(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates delete_organization when current org is not in desired."""
    mock_glitchtip_client.get_organizations.return_value = {
        "obsolete-org": Organization(pk=2, name="obsolete-org", slug="obsolete-org")
    }

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[],  # No desired orgs
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipActionDeleteOrganization)
    assert result.actions[0].organization == "obsolete-org"


def test_reconcile_invites_user(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates invite_user when desired user is missing from current."""
    mock_glitchtip_client.get_organization_users.return_value = []

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[],
                projects=[],
                users=[GlitchtipUser(email="new-user@example.com", role="member")],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipActionInviteUser)
    assert result.actions[0].email == "new-user@example.com"
    assert result.actions[0].role == "member"


def test_reconcile_deletes_user(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates delete_user when current user is not in desired."""
    mock_glitchtip_client.get_organization_users.return_value = [
        User(pk=10, email="old-user@example.com", orgRole="member")
    ]

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[GIOrganization(name="my-org", teams=[], projects=[], users=[])],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipActionDeleteUser)
    assert result.actions[0].email == "old-user@example.com"
    assert result.actions[0].pk == 10


def test_reconcile_updates_user_role(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates update_user_role when a user's role differs."""
    mock_glitchtip_client.get_organization_users.return_value = [
        User(pk=11, email="user@example.com", orgRole="member")
    ]

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[],
                projects=[],
                users=[GlitchtipUser(email="user@example.com", role="admin")],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipActionUpdateUserRole)
    assert result.actions[0].email == "user@example.com"
    assert result.actions[0].role == "admin"
    assert result.actions[0].pk == 11


def test_reconcile_creates_team(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates create_team when desired team is missing from current."""
    mock_glitchtip_client.get_teams.return_value = []

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[GlitchtipTeam(name="backend")],
                projects=[],
                users=[],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    create_team_actions = [
        a for a in result.actions if isinstance(a, GlitchtipActionCreateTeam)
    ]
    assert len(create_team_actions) == 1
    assert create_team_actions[0].team_slug == "backend"


def test_reconcile_creates_team_and_adds_members_in_single_run(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test that membership actions are generated for new teams in the same run.

    When a team does not exist yet, create_team and add_user_to_team actions should
    both be emitted so a single reconcile pass is sufficient.
    """
    mock_glitchtip_client.get_teams.return_value = []
    mock_glitchtip_client.get_organization_users.return_value = [
        User(pk=42, email="alice@example.com", role="member")
    ]

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[
                    GlitchtipTeam(
                        name="backend",
                        users=[GlitchtipUser(email="alice@example.com", role="member")],
                    )
                ],
                projects=[],
                users=[GlitchtipUser(email="alice@example.com", role="member")],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    create_team_actions = [
        a for a in result.actions if isinstance(a, GlitchtipActionCreateTeam)
    ]
    add_member_actions = [
        a for a in result.actions if isinstance(a, GlitchtipActionAddUserToTeam)
    ]
    assert len(create_team_actions) == 1
    assert create_team_actions[0].team_slug == "backend"
    assert len(add_member_actions) == 1
    assert add_member_actions[0].email == "alice@example.com"
    assert add_member_actions[0].team_slug == "backend"
    # create_team must appear before add_user_to_team in the action list
    create_idx = result.actions.index(create_team_actions[0])
    add_idx = result.actions.index(add_member_actions[0])
    assert create_idx < add_idx


def test_reconcile_deletes_team(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates delete_team when current team is not in desired."""
    mock_glitchtip_client.get_teams.return_value = [Team(pk=5, slug="old-team")]

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[GIOrganization(name="my-org", teams=[], projects=[], users=[])],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    delete_team_actions = [
        a for a in result.actions if isinstance(a, GlitchtipActionDeleteTeam)
    ]
    assert len(delete_team_actions) == 1
    assert delete_team_actions[0].team_slug == "old-team"


def test_reconcile_creates_project(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates create_project when desired project is missing from current."""
    mock_glitchtip_client.get_projects.return_value = []

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[],
                projects=[GIProject(name="api-service", slug="api-service")],
                users=[],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    create_project_actions = [
        a for a in result.actions if isinstance(a, GlitchtipActionCreateProject)
    ]
    assert len(create_project_actions) == 1
    assert create_project_actions[0].project_name == "api-service"


def test_reconcile_deletes_project(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates delete_project when current project is not in desired."""
    mock_glitchtip_client.get_projects.return_value = [
        Project(pk=20, name="old-project", slug="old-project")
    ]

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[GIOrganization(name="my-org", teams=[], projects=[], users=[])],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    delete_project_actions = [
        a for a in result.actions if isinstance(a, GlitchtipActionDeleteProject)
    ]
    assert len(delete_project_actions) == 1
    assert delete_project_actions[0].project_slug == "old-project"


def test_reconcile_updates_project(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calculates update_project when a project's platform differs."""
    mock_glitchtip_client.get_projects.return_value = [
        Project(pk=30, name="api-service", slug="api-service", platform="python")
    ]

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[],
                projects=[
                    GIProject(
                        name="api-service",
                        slug="api-service",
                        platform="javascript",  # Changed
                    )
                ],
                users=[],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    update_project_actions = [
        a for a in result.actions if isinstance(a, GlitchtipActionUpdateProject)
    ]
    assert len(update_project_actions) == 1
    assert update_project_actions[0].project_slug == "api-service"


def test_reconcile_handles_instance_error(
    service: GlitchtipService,
    test_instance: GIInstance,
    mock_glitchtip_client_factory: MagicMock,
) -> None:
    """Test reconcile returns FAILED status when an instance raises an exception."""
    mock_glitchtip_client_factory.create_workspace_client.side_effect = RuntimeError(
        "Connection refused"
    )

    result = service.reconcile(instances=[test_instance], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "Connection refused" in result.errors[0]
    assert result.applied_count == 0
    assert result.applied_actions == []


def test_reconcile_executes_actions_when_not_dry_run(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test reconcile calls invite_user on the client when dry_run=False."""
    mock_glitchtip_client.get_organization_users.return_value = []
    mock_glitchtip_client.invite_user.return_value = User(
        pk=99, email="new-user@example.com", orgRole="member"
    )

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[],
                projects=[],
                users=[GlitchtipUser(email="new-user@example.com", role="member")],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    assert len(result.applied_actions) == 1
    assert isinstance(result.applied_actions[0], GlitchtipActionInviteUser)
    mock_glitchtip_client.invite_user.assert_called_once()


def test_reconcile_records_error_when_add_user_to_team_pk_unresolvable(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test that a failed invite causes add_user_to_team to record an error.

    When a user is invited and added to a team in the same run, the pk is
    resolved at execution time. If the invite failed, the user won't exist and
    pk stays None — this must be recorded as an error, not silently skipped.
    """
    # Invite fails: get_organization_users returns empty list (user not found)
    mock_glitchtip_client.get_organization_users.return_value = []
    mock_glitchtip_client.invite_user.side_effect = RuntimeError("Invite failed")
    mock_glitchtip_client.get_teams.return_value = [
        Team(pk=1, slug="backend", isMember=False)
    ]
    mock_glitchtip_client.get_team_users.return_value = []

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[
                    GlitchtipTeam(
                        name="backend",
                        users=[
                            GlitchtipUser(email="new-user@example.com", role="member")
                        ],
                    )
                ],
                projects=[],
                users=[GlitchtipUser(email="new-user@example.com", role="member")],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=False)

    assert result.status == TaskStatus.FAILED
    # invite_user error + add_user_to_team unresolvable pk error
    assert len(result.errors) == 2
    assert any("Invite failed" in e for e in result.errors)
    assert any("new-user@example.com" in e for e in result.errors)
    # Neither action should be in applied_actions
    assert result.applied_count == 0
    mock_glitchtip_client.add_user_to_team.assert_not_called()


def test_reconcile_ignores_automation_user(
    mock_glitchtip_client_factory: MagicMock,
    mock_glitchtip_client: MagicMock,
    mock_settings: Settings,
    test_token: Secret,
    test_automation_email_secret: Secret,
) -> None:
    """Test that the automation user is excluded from user diffs and not deleted."""
    # The automation user is in current state but NOT in desired state.
    # It should be excluded from diffs so no delete_user action is generated.
    mock_glitchtip_client.get_organization_users.return_value = [
        User(pk=1, email="bot@example.com", orgRole="admin")
    ]

    # Secret manager returns different values depending on which secret is read:
    # token → "test-token", automation_user_email → "bot@example.com"
    mock_secret_manager = MagicMock()

    def _read_secret(secret: Secret) -> str:
        if secret.path == test_automation_email_secret.path:
            return "bot@example.com"
        return "test-token"

    mock_secret_manager.read.side_effect = _read_secret

    service = GlitchtipService(
        glitchtip_client_factory=mock_glitchtip_client_factory,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            # Desired state: no users — but automation user should be ignored
            GIOrganization(name="my-org", teams=[], projects=[], users=[])
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    # No delete_user action should be present for the automation user
    delete_user_actions = [
        a for a in result.actions if isinstance(a, GlitchtipActionDeleteUser)
    ]
    assert delete_user_actions == []


def test_reconcile_delete_team_skips_remove_project_from_team(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test that remove_project_from_team is not planned when the team is being deleted.

    GlitchTip auto-removes project-team associations when a team is deleted,
    so planning an explicit remove_project_from_team would 404.
    """
    mock_glitchtip_client.get_teams.return_value = [Team(pk=5, slug="old-team")]
    mock_glitchtip_client.get_projects.return_value = [
        Project(pk=10, name="my-project", slug="my-project", team_slugs=["old-team"])
    ]

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[],
                projects=[GIProject(name="my-project", slug="my-project", teams=[])],
                users=[],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert any(isinstance(a, GlitchtipActionDeleteTeam) for a in result.actions)
    assert not any(
        isinstance(a, GlitchtipActionRemoveProjectFromTeam) for a in result.actions
    )


def test_reconcile_delete_user_skips_remove_user_from_team(
    service: GlitchtipService,
    test_token: Secret,
    test_automation_email_secret: Secret,
    mock_glitchtip_client: MagicMock,
) -> None:
    """Test that remove_user_from_team is not planned when the user is being deleted.

    GlitchTip auto-removes team memberships when a user is deleted from an org,
    so planning an explicit remove_user_from_team would 404.
    """
    mock_glitchtip_client.get_organization_users.return_value = [
        User(pk=7, email="leaving@example.com", orgRole="member")
    ]
    mock_glitchtip_client.get_teams.return_value = [Team(pk=5, slug="my-team")]
    mock_glitchtip_client.get_team_users.return_value = [
        User(pk=7, email="leaving@example.com", orgRole="member")
    ]

    instance = GIInstance(
        name="test-instance",
        console_url="https://glitchtip.example.com",
        token=test_token,
        automation_user_email=test_automation_email_secret,
        organizations=[
            GIOrganization(
                name="my-org",
                teams=[GlitchtipTeam(name="my-team", users=[])],
                projects=[],
                users=[],
            )
        ],
    )

    result = service.reconcile(instances=[instance], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert any(isinstance(a, GlitchtipActionDeleteUser) for a in result.actions)
    assert not any(
        isinstance(a, GlitchtipActionRemoveUserFromTeam) for a in result.actions
    )
