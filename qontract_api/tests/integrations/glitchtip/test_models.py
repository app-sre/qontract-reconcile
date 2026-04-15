"""Unit tests for Glitchtip domain and schema models."""

from typing import Any

from qontract_api.integrations.glitchtip.domain import (
    GIInstance,
    GIOrganization,
    GIProject,
    GlitchtipTeam,
    GlitchtipUser,
)
from qontract_api.integrations.glitchtip.schemas import (
    GlitchtipActionAddProjectToTeam,
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
    GlitchtipReconcileRequest,
    GlitchtipTaskResponse,
    GlitchtipTaskResult,
)
from qontract_api.models import Secret, TaskStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_secret(path: str = "secret/glitchtip/token") -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.com",
        path=path,
    )


def _make_instance(**kwargs: Any) -> GIInstance:
    defaults: dict[str, Any] = {
        "name": "my-instance",
        "console_url": "https://glitchtip.example.com",
        "token": _make_secret("secret/glitchtip/token"),
        "automation_user_email": _make_secret("secret/glitchtip/automation-email"),
    }
    defaults.update(kwargs)
    return GIInstance(**defaults)


# ---------------------------------------------------------------------------
# GlitchtipUser
# ---------------------------------------------------------------------------


def test_glitchtip_user_defaults() -> None:
    """Test GlitchtipUser role defaults to 'member'."""
    user = GlitchtipUser(email="user@example.com")
    assert user.email == "user@example.com"
    assert user.role == "member"


def test_glitchtip_user_explicit_role() -> None:
    """Test GlitchtipUser accepts an explicit role."""
    user = GlitchtipUser(email="admin@example.com", role="admin")
    assert user.role == "admin"


# ---------------------------------------------------------------------------
# GlitchtipTeam
# ---------------------------------------------------------------------------


def test_glitchtip_team_defaults() -> None:
    """Test GlitchtipTeam users default to empty list."""
    team = GlitchtipTeam(name="backend")
    assert team.name == "backend"
    assert team.users == []


def test_glitchtip_team_with_users() -> None:
    """Test GlitchtipTeam with a list of users."""
    team = GlitchtipTeam(
        name="backend",
        users=[GlitchtipUser(email="dev@example.com")],
    )
    assert len(team.users) == 1
    assert team.users[0].email == "dev@example.com"


# ---------------------------------------------------------------------------
# GIProject
# ---------------------------------------------------------------------------


def test_gi_project_defaults() -> None:
    """Test GIProject default values."""
    project = GIProject(name="my-project", slug="my-project")
    assert project.name == "my-project"
    assert project.slug == "my-project"
    assert project.platform is None
    assert project.event_throttle_rate == 0
    assert project.teams == []


def test_gi_project_with_platform_and_teams() -> None:
    """Test GIProject with all fields specified."""
    project = GIProject(
        name="frontend",
        slug="frontend",
        platform="javascript",
        event_throttle_rate=50,
        teams=["team-a", "team-b"],
    )
    assert project.platform == "javascript"
    assert project.event_throttle_rate == 50
    assert project.teams == ["team-a", "team-b"]


# ---------------------------------------------------------------------------
# GIOrganization
# ---------------------------------------------------------------------------


def test_gi_organization_fields() -> None:
    """Test GIOrganization stores name, teams, projects, and users."""
    org = GIOrganization(
        name="my-org",
        teams=[GlitchtipTeam(name="backend")],
        projects=[GIProject(name="api", slug="api")],
        users=[GlitchtipUser(email="user@example.com")],
    )
    assert org.name == "my-org"
    assert len(org.teams) == 1
    assert len(org.projects) == 1
    assert len(org.users) == 1


def test_gi_organization_defaults() -> None:
    """Test GIOrganization has empty lists by default."""
    org = GIOrganization(name="empty-org", teams=[], projects=[], users=[])
    assert org.teams == []
    assert org.projects == []
    assert org.users == []


# ---------------------------------------------------------------------------
# GIInstance
# ---------------------------------------------------------------------------


def test_gi_instance_defaults() -> None:
    """Test GIInstance default values for read_timeout, max_retries, organizations."""
    instance = _make_instance()
    assert instance.name == "my-instance"
    assert instance.console_url == "https://glitchtip.example.com"
    assert instance.read_timeout == 30
    assert instance.max_retries == 3
    assert instance.organizations == []


def test_gi_instance_with_organizations() -> None:
    """Test GIInstance stores organizations correctly."""
    instance = _make_instance(
        organizations=[GIOrganization(name="org-1", teams=[], projects=[], users=[])]
    )
    assert len(instance.organizations) == 1
    assert instance.organizations[0].name == "org-1"


def test_gi_instance_automation_user_email_is_secret() -> None:
    """Test that automation_user_email is a Secret object."""
    instance = _make_instance()
    assert isinstance(instance.automation_user_email, Secret)
    assert isinstance(instance.token, Secret)


# ---------------------------------------------------------------------------
# GlitchtipReconcileRequest
# ---------------------------------------------------------------------------


def test_glitchtip_reconcile_request_default_dry_run() -> None:
    """Test that dry_run defaults to True (safety first)."""
    request = GlitchtipReconcileRequest(instances=[])
    assert request.dry_run is True


def test_glitchtip_reconcile_request_explicit_dry_run_false() -> None:
    """Test that dry_run can be set to False explicitly."""
    request = GlitchtipReconcileRequest(instances=[], dry_run=False)
    assert request.dry_run is False


def test_glitchtip_reconcile_request_with_instances() -> None:
    """Test GlitchtipReconcileRequest stores instances."""
    request = GlitchtipReconcileRequest(
        instances=[_make_instance()],
        dry_run=True,
    )
    assert len(request.instances) == 1
    assert request.dry_run is True


# ---------------------------------------------------------------------------
# Action models — all 14 action_type literals
# ---------------------------------------------------------------------------


def test_action_create_organization() -> None:
    """Test GlitchtipActionCreateOrganization action_type literal."""
    action = GlitchtipActionCreateOrganization(
        instance="my-instance", organization="my-org"
    )
    assert action.action_type == "create_organization"
    assert action.instance == "my-instance"
    assert action.organization == "my-org"


def test_action_delete_organization() -> None:
    """Test GlitchtipActionDeleteOrganization action_type literal."""
    action = GlitchtipActionDeleteOrganization(
        instance="my-instance", organization="my-org"
    )
    assert action.action_type == "delete_organization"
    assert action.instance == "my-instance"
    assert action.organization == "my-org"


def test_action_invite_user() -> None:
    """Test GlitchtipActionInviteUser action_type literal and fields."""
    action = GlitchtipActionInviteUser(
        instance="my-instance",
        organization="my-org",
        email="user@example.com",
        role="member",
    )
    assert action.action_type == "invite_user"
    assert action.email == "user@example.com"
    assert action.role == "member"


def test_action_delete_user() -> None:
    """Test GlitchtipActionDeleteUser action_type literal."""
    action = GlitchtipActionDeleteUser(
        instance="my-instance", organization="my-org", email="user@example.com", pk=42
    )
    assert action.action_type == "delete_user"
    assert action.email == "user@example.com"
    assert action.pk == 42


def test_action_update_user_role() -> None:
    """Test GlitchtipActionUpdateUserRole action_type literal."""
    action = GlitchtipActionUpdateUserRole(
        instance="my-instance",
        organization="my-org",
        email="user@example.com",
        role="admin",
        pk=42,
    )
    assert action.action_type == "update_user_role"
    assert action.role == "admin"
    assert action.pk == 42


def test_action_create_team() -> None:
    """Test GlitchtipActionCreateTeam action_type literal."""
    action = GlitchtipActionCreateTeam(
        instance="my-instance", organization="my-org", team_slug="backend"
    )
    assert action.action_type == "create_team"
    assert action.team_slug == "backend"


def test_action_delete_team() -> None:
    """Test GlitchtipActionDeleteTeam action_type literal."""
    action = GlitchtipActionDeleteTeam(
        instance="my-instance", organization="my-org", team_slug="old-team"
    )
    assert action.action_type == "delete_team"
    assert action.team_slug == "old-team"


def test_action_add_user_to_team() -> None:
    """Test GlitchtipActionAddUserToTeam action_type literal and optional pk."""
    action = GlitchtipActionAddUserToTeam(
        instance="my-instance",
        organization="my-org",
        team_slug="backend",
        email="dev@example.com",
        pk=7,
    )
    assert action.action_type == "add_user_to_team"
    assert action.team_slug == "backend"
    assert action.email == "dev@example.com"
    assert action.pk == 7


def test_action_add_user_to_team_pk_defaults_to_none() -> None:
    """Test GlitchtipActionAddUserToTeam pk defaults to None for newly invited users."""
    action = GlitchtipActionAddUserToTeam(
        instance="my-instance",
        organization="my-org",
        team_slug="backend",
        email="new@example.com",
    )
    assert action.pk is None


def test_action_remove_user_from_team() -> None:
    """Test GlitchtipActionRemoveUserFromTeam action_type literal."""
    action = GlitchtipActionRemoveUserFromTeam(
        instance="my-instance",
        organization="my-org",
        team_slug="backend",
        email="dev@example.com",
        pk=7,
    )
    assert action.action_type == "remove_user_from_team"
    assert action.team_slug == "backend"
    assert action.email == "dev@example.com"
    assert action.pk == 7


def test_action_create_project() -> None:
    """Test GlitchtipActionCreateProject action_type literal."""
    action = GlitchtipActionCreateProject(
        instance="my-instance",
        organization="my-org",
        project_name="api-service",
        platform="python",
        event_throttle_rate=100,
        teams=["backend", "frontend"],
    )
    assert action.action_type == "create_project"
    assert action.project_name == "api-service"
    assert action.platform == "python"
    assert action.event_throttle_rate == 100
    assert action.teams == ["backend", "frontend"]


def test_action_update_project() -> None:
    """Test GlitchtipActionUpdateProject action_type literal."""
    action = GlitchtipActionUpdateProject(
        instance="my-instance",
        organization="my-org",
        project_slug="api-service",
        name="API Service",
        platform="python",
        event_throttle_rate=50,
    )
    assert action.action_type == "update_project"
    assert action.project_slug == "api-service"
    assert action.name == "API Service"
    assert action.platform == "python"
    assert action.event_throttle_rate == 50


def test_action_delete_project() -> None:
    """Test GlitchtipActionDeleteProject action_type literal."""
    action = GlitchtipActionDeleteProject(
        instance="my-instance", organization="my-org", project_slug="old-project"
    )
    assert action.action_type == "delete_project"
    assert action.project_slug == "old-project"


def test_action_add_project_to_team() -> None:
    """Test GlitchtipActionAddProjectToTeam action_type literal."""
    action = GlitchtipActionAddProjectToTeam(
        instance="my-instance",
        organization="my-org",
        project_slug="api-service",
        team_slug="backend",
    )
    assert action.action_type == "add_project_to_team"
    assert action.project_slug == "api-service"
    assert action.team_slug == "backend"


def test_action_remove_project_from_team() -> None:
    """Test GlitchtipActionRemoveProjectFromTeam action_type literal."""
    action = GlitchtipActionRemoveProjectFromTeam(
        instance="my-instance",
        organization="my-org",
        project_slug="api-service",
        team_slug="backend",
    )
    assert action.action_type == "remove_project_from_team"
    assert action.project_slug == "api-service"
    assert action.team_slug == "backend"


# ---------------------------------------------------------------------------
# GlitchtipTaskResult
# ---------------------------------------------------------------------------


def test_glitchtip_task_result_defaults() -> None:
    """Test GlitchtipTaskResult default values for actions, applied_count, errors."""
    result = GlitchtipTaskResult(status=TaskStatus.SUCCESS)
    assert result.actions == []
    assert result.applied_count == 0
    assert result.errors == []


def test_glitchtip_task_result_with_actions() -> None:
    """Test GlitchtipTaskResult with populated fields."""
    result = GlitchtipTaskResult(
        status=TaskStatus.SUCCESS,
        actions=[
            GlitchtipActionCreateOrganization(
                instance="my-instance", organization="new-org"
            )
        ],
        applied_count=1,
        errors=[],
    )
    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], GlitchtipActionCreateOrganization)
    assert result.applied_count == 1


def test_glitchtip_task_result_failed_with_errors() -> None:
    """Test GlitchtipTaskResult in FAILED state with errors."""
    result = GlitchtipTaskResult(
        status=TaskStatus.FAILED,
        errors=["Something went wrong"],
    )
    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "Something went wrong" in result.errors[0]


# ---------------------------------------------------------------------------
# GlitchtipTaskResponse
# ---------------------------------------------------------------------------


def test_glitchtip_task_response() -> None:
    """Test GlitchtipTaskResponse stores id, status, and status_url."""
    response = GlitchtipTaskResponse(
        id="task-abc-123",
        status=TaskStatus.PENDING,
        status_url="https://api.example.com/reconcile/task-abc-123",
    )
    assert response.id == "task-abc-123"
    assert response.status == TaskStatus.PENDING
    assert "task-abc-123" in response.status_url


def test_glitchtip_task_response_default_status() -> None:
    """Test GlitchtipTaskResponse status defaults to PENDING."""
    response = GlitchtipTaskResponse(
        id="task-xyz",
        status_url="https://api.example.com/reconcile/task-xyz",
    )
    assert response.status == TaskStatus.PENDING
