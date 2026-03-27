"""Unit tests for GlitchtipService._calculate_actions (single-pass org convergence)."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.glitchtip_api.models import Organization

from qontract_api.glitchtip import GlitchtipWorkspaceClient
from qontract_api.integrations.glitchtip.domain import (
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
    GlitchtipActionInviteUser,
)
from qontract_api.integrations.glitchtip.service import GlitchtipService


@pytest.fixture
def mock_glitchtip() -> MagicMock:
    """GlitchtipWorkspaceClient with empty current state."""
    mock = MagicMock(spec=GlitchtipWorkspaceClient)
    mock.get_organizations.return_value = {}
    mock.get_organization_users.return_value = []
    mock.get_teams.return_value = []
    mock.get_team_users.return_value = []
    mock.get_projects.return_value = []
    return mock


def _calculate(
    glitchtip: MagicMock,
    organizations: list[GIOrganization],
    *,
    ignore_user_email: str = "bot@example.com",
) -> list:
    return GlitchtipService._calculate_actions(
        instance_name="test",
        glitchtip=glitchtip,
        organizations=organizations,
        ignore_user_email=ignore_user_email,
    )


# ---------------------------------------------------------------------------
# New org — single-pass convergence
# ---------------------------------------------------------------------------


def test_new_org_generates_create_org_action(mock_glitchtip: MagicMock) -> None:
    """CreateOrganization is generated for an org not in current state."""
    org = GIOrganization(name="new-org")
    actions = _calculate(mock_glitchtip, [org])

    assert any(
        isinstance(a, GlitchtipActionCreateOrganization) and a.organization == "new-org"
        for a in actions
    )


def test_new_org_invite_users_in_same_pass(mock_glitchtip: MagicMock) -> None:
    """InviteUser actions are generated for all desired users of a new org."""
    org = GIOrganization(
        name="new-org",
        users=[
            GlitchtipUser(email="alice@example.com", role="admin"),
            GlitchtipUser(email="bob@example.com", role="member"),
        ],
    )
    actions = _calculate(mock_glitchtip, [org])

    invite_actions = [a for a in actions if isinstance(a, GlitchtipActionInviteUser)]
    assert {a.email for a in invite_actions} == {"alice@example.com", "bob@example.com"}


def test_new_org_create_teams_in_same_pass(mock_glitchtip: MagicMock) -> None:
    """CreateTeam actions are generated for all desired teams of a new org."""
    org = GIOrganization(
        name="new-org",
        teams=[
            GlitchtipTeam(name="backend"),
            GlitchtipTeam(name="frontend"),
        ],
    )
    actions = _calculate(mock_glitchtip, [org])

    team_slugs = {
        a.team_slug for a in actions if isinstance(a, GlitchtipActionCreateTeam)
    }
    assert "backend" in team_slugs
    assert "frontend" in team_slugs


def test_new_org_add_users_to_teams_in_same_pass(mock_glitchtip: MagicMock) -> None:
    """AddUserToTeam actions are generated for team members of a new org."""
    org = GIOrganization(
        name="new-org",
        teams=[
            GlitchtipTeam(
                name="backend",
                users=[GlitchtipUser(email="alice@example.com", role="member")],
            )
        ],
    )
    actions = _calculate(mock_glitchtip, [org])

    add_actions = [a for a in actions if isinstance(a, GlitchtipActionAddUserToTeam)]
    assert len(add_actions) == 1
    assert add_actions[0].email == "alice@example.com"
    assert add_actions[0].team_slug == "backend"


def test_new_org_create_projects_in_same_pass(mock_glitchtip: MagicMock) -> None:
    """CreateProject actions are generated for all desired projects of a new org."""
    org = GIOrganization(
        name="new-org",
        projects=[
            GIProject(name="api", slug="api", teams=["backend"]),
            GIProject(name="web", slug="web", teams=["frontend"]),
        ],
    )
    actions = _calculate(mock_glitchtip, [org])

    project_names = {
        a.project_name for a in actions if isinstance(a, GlitchtipActionCreateProject)
    }
    assert project_names == {"api", "web"}


def test_new_org_action_ordering(mock_glitchtip: MagicMock) -> None:
    """CreateOrganization precedes all child actions for a new org."""
    org = GIOrganization(
        name="new-org",
        users=[GlitchtipUser(email="alice@example.com", role="member")],
        teams=[GlitchtipTeam(name="backend")],
        projects=[GIProject(name="api", slug="api", teams=["backend"])],
    )
    actions = _calculate(mock_glitchtip, [org])

    create_org_idx = next(
        i
        for i, a in enumerate(actions)
        if isinstance(a, GlitchtipActionCreateOrganization)
    )
    child_indices = [
        i
        for i, a in enumerate(actions)
        if isinstance(
            a,
            GlitchtipActionInviteUser
            | GlitchtipActionCreateTeam
            | GlitchtipActionAddUserToTeam
            | GlitchtipActionCreateProject,
        )
    ]
    assert all(create_org_idx < idx for idx in child_indices)


def test_new_org_no_api_calls_for_child_state(mock_glitchtip: MagicMock) -> None:
    """Child actions for new org are calculated without querying per-org API endpoints."""
    org = GIOrganization(
        name="new-org",
        users=[GlitchtipUser(email="alice@example.com", role="member")],
        teams=[GlitchtipTeam(name="backend")],
        projects=[GIProject(name="api", slug="api", teams=["backend"])],
    )
    _calculate(mock_glitchtip, [org])

    mock_glitchtip.get_organization_users.assert_not_called()
    mock_glitchtip.get_teams.assert_not_called()
    mock_glitchtip.get_projects.assert_not_called()


# ---------------------------------------------------------------------------
# Existing org — normal diff behavior unchanged
# ---------------------------------------------------------------------------


def test_existing_org_no_actions_when_in_sync(mock_glitchtip: MagicMock) -> None:
    """No actions when existing org matches desired state."""
    mock_glitchtip.get_organizations.return_value = {
        "my-org": Organization(pk=1, name="my-org", slug="my-org")
    }
    org = GIOrganization(name="my-org")
    actions = _calculate(mock_glitchtip, [org])

    assert actions == []


def test_obsolete_org_generates_delete_last(mock_glitchtip: MagicMock) -> None:
    """DeleteOrganization is generated for orgs in current state but not desired, and is last."""
    mock_glitchtip.get_organizations.return_value = {
        "old-org": Organization(pk=1, name="old-org", slug="old-org"),
    }
    actions = _calculate(mock_glitchtip, [])

    assert len(actions) == 1
    assert isinstance(actions[-1], GlitchtipActionDeleteOrganization)
    assert actions[-1].organization == "old-org"


# ---------------------------------------------------------------------------
# Mixed scenario: new org + existing org in same run
# ---------------------------------------------------------------------------


def test_new_and_existing_org_together(mock_glitchtip: MagicMock) -> None:
    """New org gets full child creates; existing org gets normal diff; obsolete org deleted last."""
    mock_glitchtip.get_organizations.return_value = {
        "existing-org": Organization(pk=1, name="existing-org", slug="existing-org"),
        "obsolete-org": Organization(pk=2, name="obsolete-org", slug="obsolete-org"),
    }
    mock_glitchtip.get_organization_users.return_value = []
    mock_glitchtip.get_teams.return_value = []
    mock_glitchtip.get_projects.return_value = []

    orgs = [
        GIOrganization(
            name="new-org",
            users=[GlitchtipUser(email="alice@example.com", role="member")],
        ),
        GIOrganization(name="existing-org"),
    ]
    actions = _calculate(mock_glitchtip, orgs)

    action_types = [type(a) for a in actions]

    # New org: CreateOrg + InviteUser
    assert GlitchtipActionCreateOrganization in action_types
    assert GlitchtipActionInviteUser in action_types

    # Obsolete org: DeleteOrganization (last)
    assert isinstance(actions[-1], GlitchtipActionDeleteOrganization)
    assert actions[-1].organization == "obsolete-org"
