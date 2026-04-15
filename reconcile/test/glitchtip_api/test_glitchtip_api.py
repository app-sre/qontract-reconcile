"""Unit tests for the GlitchtipApiIntegration helper methods."""

import asyncio

import pytest
from pytest_mock import MockerFixture
from qontract_api_client.models.gi_organization import GIOrganization
from qontract_api_client.models.glitchtip_user import GlitchtipUser
from qontract_utils.glitchtip_api import slugify

from reconcile.glitchtip_api.integration import (
    DEFAULT_MEMBER_ROLE,
    GlitchtipApiIntegration,
    _get_user_role,
    _highest_role,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    AppEscalationPolicyChannelsV1,
    AppEscalationPolicyV1,
    AppV1,
    GlitchtipInstanceV1,
    GlitchtipOrganizationV1,
    GlitchtipProjectV1,
    GlitchtipProjectV1_GlitchtipOrganizationV1,
    GlitchtipRoleV1,
    GlitchtipTeamV1,
    RoleV1,
    UserV1,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAIL_DOMAIN = "example.com"
LDAP_API_URL = "https://ldap.example.com"
LDAP_TOKEN_URL = "https://ldap.example.com/token"
LDAP_CLIENT_ID = "test-client-id"
LDAP_CRED_PATH = "secret/ldap/creds"
LDAP_CRED_VERSION: int | None = None

ORG_NAME = "my-org"
INSTANCE_NAME = "glitchtip-dev"


def make_integration() -> GlitchtipApiIntegration:
    """Return a bare GlitchtipApiIntegration instance without calling __init__."""
    return GlitchtipApiIntegration.__new__(GlitchtipApiIntegration)


def make_organization(
    name: str = ORG_NAME,
) -> GlitchtipProjectV1_GlitchtipOrganizationV1:
    return GlitchtipProjectV1_GlitchtipOrganizationV1(
        name=name,
        instance=GlitchtipInstanceV1(name=INSTANCE_NAME),
        owners=None,
    )


def make_role(
    org_name: str,
    role_str: str,
    usernames: list[str],
) -> RoleV1:
    """Build a RoleV1 with a single GlitchtipRoleV1 entry and the specified users."""
    return RoleV1(
        glitchtip_roles=[
            GlitchtipRoleV1(
                organization=GlitchtipOrganizationV1(name=org_name),
                role=role_str,
            )
        ],
        users=[UserV1(name=username, org_username=username) for username in usernames],
    )


def make_team(
    name: str,
    roles: list[RoleV1] | None = None,
    ldap_groups: list[str] | None = None,
    members_organization_role: str | None = None,
) -> GlitchtipTeamV1:
    return GlitchtipTeamV1(
        name=name,
        roles=roles or [],
        ldapGroups=ldap_groups,
        membersOrganizationRole=members_organization_role,
    )


# ---------------------------------------------------------------------------
# _highest_role
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role_a", "role_b", "expected"),
    [
        ("admin", "member", "admin"),
        ("member", "admin", "admin"),
        ("member", "member", "member"),
        ("manager", "contributor", "manager"),
        ("owner", "admin", "owner"),
        # Unknown roles lose to any known role
        ("unknown", "member", "member"),
        ("admin", "unknown", "admin"),
    ],
)
def test_highest_role(role_a: str, role_b: str, expected: str) -> None:
    assert _highest_role(role_a, role_b) == expected


# ---------------------------------------------------------------------------
# _get_user_role
# ---------------------------------------------------------------------------


def test_get_user_role_found() -> None:
    """When a role has a matching organization, the defined role string is returned."""
    org = make_organization(ORG_NAME)
    role = make_role(org_name=ORG_NAME, role_str="admin", usernames=["alice"])

    result = _get_user_role(org, role)

    assert result == "admin"


def test_get_user_role_not_found() -> None:
    """When no glitchtip_role matches the organization, DEFAULT_MEMBER_ROLE is returned."""
    org = make_organization(ORG_NAME)
    role = make_role(org_name="other-org", role_str="owner", usernames=["bob"])

    result = _get_user_role(org, role)

    assert result == DEFAULT_MEMBER_ROLE


def test_get_user_role_no_glitchtip_roles() -> None:
    """When glitchtip_roles is None, DEFAULT_MEMBER_ROLE is returned."""
    org = make_organization(ORG_NAME)
    role = RoleV1(
        glitchtip_roles=None,
        users=[UserV1(name="charlie", org_username="charlie")],
    )

    result = _get_user_role(org, role)

    assert result == DEFAULT_MEMBER_ROLE


def test_get_user_role_first_matching_org_wins() -> None:
    """When multiple glitchtip_roles exist, the first matching org is returned."""
    org = make_organization(ORG_NAME)
    role = RoleV1(
        glitchtip_roles=[
            GlitchtipRoleV1(
                organization=GlitchtipOrganizationV1(name="other-org"),
                role="owner",
            ),
            GlitchtipRoleV1(
                organization=GlitchtipOrganizationV1(name=ORG_NAME),
                role="contributor",
            ),
        ],
        users=[UserV1(name="dave", org_username="dave")],
    )

    result = _get_user_role(org, role)

    assert result == "contributor"


# ---------------------------------------------------------------------------
# _build_team_users
# ---------------------------------------------------------------------------


def _run_build_team_users(
    glitchtip_team: GlitchtipTeamV1,
    organization: GlitchtipProjectV1_GlitchtipOrganizationV1,
    ldap_members: dict[str, list[str]] | None = None,
) -> dict[str, GlitchtipUser]:
    """Helper to call the (now sync) _build_team_users static method."""
    return GlitchtipApiIntegration._build_team_users(
        glitchtip_team=glitchtip_team,
        organization=organization,
        mail_domain=MAIL_DOMAIN,
        ldap_members=ldap_members or {},
    )


def test_build_team_users_from_roles() -> None:
    """Users defined in roles are added with their org-specific role."""
    org = make_organization(ORG_NAME)
    team = make_team(
        name="backend-team",
        roles=[
            make_role(org_name=ORG_NAME, role_str="admin", usernames=["alice", "bob"])
        ],
    )

    result = _run_build_team_users(team, org)

    assert result == {
        f"alice@{MAIL_DOMAIN}": GlitchtipUser(
            email=f"alice@{MAIL_DOMAIN}", role="admin"
        ),
        f"bob@{MAIL_DOMAIN}": GlitchtipUser(email=f"bob@{MAIL_DOMAIN}", role="admin"),
    }


def test_build_team_users_role_not_matching_org_uses_default() -> None:
    """A role whose glitchtip_roles don't match the org still produces DEFAULT_MEMBER_ROLE users."""
    org = make_organization(ORG_NAME)
    team = make_team(
        name="frontend-team",
        roles=[
            make_role(
                org_name="completely-different-org",
                role_str="owner",
                usernames=["carol"],
            )
        ],
    )

    result = _run_build_team_users(team, org)

    assert result == {
        f"carol@{MAIL_DOMAIN}": GlitchtipUser(
            email=f"carol@{MAIL_DOMAIN}", role=DEFAULT_MEMBER_ROLE
        ),
    }


def test_build_team_users_from_ldap() -> None:
    """Members from the pre-fetched ldap_members cache are added with the team's role."""
    org = make_organization(ORG_NAME)
    team = make_team(
        name="infra-team",
        roles=[],
        ldap_groups=["ldap-group-a"],
        members_organization_role="contributor",
    )

    result = _run_build_team_users(
        team, org, ldap_members={"ldap-group-a": ["user1", "user2"]}
    )

    assert result == {
        f"user1@{MAIL_DOMAIN}": GlitchtipUser(
            email=f"user1@{MAIL_DOMAIN}", role="contributor"
        ),
        f"user2@{MAIL_DOMAIN}": GlitchtipUser(
            email=f"user2@{MAIL_DOMAIN}", role="contributor"
        ),
    }


def test_build_team_users_ldap_no_members_org_role_uses_default() -> None:
    """When members_organization_role is None, LDAP members get DEFAULT_MEMBER_ROLE."""
    org = make_organization(ORG_NAME)
    team = make_team(
        name="ops-team",
        roles=[],
        ldap_groups=["some-group"],
        members_organization_role=None,
    )

    result = _run_build_team_users(
        team, org, ldap_members={"some-group": ["ldap-user"]}
    )

    assert result == {
        f"ldap-user@{MAIL_DOMAIN}": GlitchtipUser(
            email=f"ldap-user@{MAIL_DOMAIN}", role=DEFAULT_MEMBER_ROLE
        ),
    }


def test_build_team_users_roles_take_precedence_over_ldap() -> None:
    """When a user appears in both roles and LDAP, the role entry wins."""
    org = make_organization(ORG_NAME)
    team = make_team(
        name="mixed-team",
        roles=[make_role(org_name=ORG_NAME, role_str="admin", usernames=["alice"])],
        ldap_groups=["some-group"],
        members_organization_role="member",
    )

    # "alice" is also in LDAP, but should keep her role-defined "admin" role
    result = _run_build_team_users(
        team, org, ldap_members={"some-group": ["alice", "ldap-only-user"]}
    )

    assert result[f"alice@{MAIL_DOMAIN}"].role == "admin"
    assert result[f"ldap-only-user@{MAIL_DOMAIN}"].role == DEFAULT_MEMBER_ROLE


def test_build_team_users_multiple_ldap_groups() -> None:
    """Members from multiple LDAP groups are merged together."""
    org = make_organization(ORG_NAME)
    team = make_team(
        name="multi-ldap-team",
        roles=[],
        ldap_groups=["group-a", "group-b"],
        members_organization_role="member",
    )

    result = _run_build_team_users(
        team,
        org,
        ldap_members={"group-a": ["user-a1", "user-a2"], "group-b": ["user-b1"]},
    )

    assert set(result.keys()) == {
        f"user-a1@{MAIL_DOMAIN}",
        f"user-a2@{MAIL_DOMAIN}",
        f"user-b1@{MAIL_DOMAIN}",
    }


# ---------------------------------------------------------------------------
# _build_desired_state
# ---------------------------------------------------------------------------


def _run_build_desired_state(
    integration: GlitchtipApiIntegration,
    glitchtip_projects: list[GlitchtipProjectV1],
) -> list[GIOrganization]:
    """Helper to synchronously run the async _build_desired_state method."""
    return asyncio.run(
        integration._build_desired_state(
            glitchtip_projects=glitchtip_projects,
            mail_domain=MAIL_DOMAIN,
            ldap_api_url=LDAP_API_URL,
            ldap_token_url=LDAP_TOKEN_URL,
            ldap_client_id=LDAP_CLIENT_ID,
            ldap_cred_path=LDAP_CRED_PATH,
            ldap_cred_version=LDAP_CRED_VERSION,
        )
    )


def make_gql_project(
    project_name: str,
    org_name: str,
    teams: list[GlitchtipTeamV1],
    platform: str = "python",
    project_id: str | None = None,
    event_throttle_rate: int | None = None,
) -> GlitchtipProjectV1:
    """Build a minimal GlitchtipProjectV1 using keyword constructor."""
    return GlitchtipProjectV1(
        name=project_name,
        platform=platform,
        projectId=project_id,
        eventThrottleRate=event_throttle_rate,
        teams=teams,
        organization=GlitchtipProjectV1_GlitchtipOrganizationV1(
            name=org_name,
            instance=GlitchtipInstanceV1(name=INSTANCE_NAME),
            owners=None,
        ),
        namespaces=[],
        app=AppV1(
            path=f"/services/{project_name}/app.yml",
            escalationPolicy=AppEscalationPolicyV1(
                channels=AppEscalationPolicyChannelsV1(jiraBoard=[])
            ),
        ),
    )


def test_build_desired_state_basic(mocker: MockerFixture) -> None:
    """One org with one project and one team produces correct GIOrganization."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    team = make_team(
        name="Alpha Team",
        roles=[make_role(org_name=ORG_NAME, role_str="admin", usernames=["alice"])],
    )
    project = make_gql_project(
        project_name="my-project",
        org_name=ORG_NAME,
        teams=[team],
        platform="python",
        event_throttle_rate=100,
    )

    orgs = _run_build_desired_state(integration, [project])

    assert len(orgs) == 1
    org = orgs[0]
    assert org.name == ORG_NAME

    # Teams
    assert isinstance(org.teams, list)
    assert len(org.teams) == 1
    assert org.teams[0].name == "Alpha Team"
    team_users = org.teams[0].users
    assert isinstance(team_users, list)
    assert len(team_users) == 1
    assert team_users[0].email == f"alice@{MAIL_DOMAIN}"
    assert team_users[0].role == "admin"

    # Projects
    assert isinstance(org.projects, list)
    assert len(org.projects) == 1
    gi_project = org.projects[0]
    assert gi_project.name == "my-project"
    assert gi_project.slug == slugify("my-project")
    assert gi_project.platform == "python"
    assert gi_project.event_throttle_rate == 100
    assert gi_project.teams == [slugify("Alpha Team")]

    # Org-level users
    assert isinstance(org.users, list)
    assert len(org.users) == 1
    assert org.users[0].email == f"alice@{MAIL_DOMAIN}"


def test_build_desired_state_uses_project_id_as_slug(mocker: MockerFixture) -> None:
    """When project_id is set, it is used as the project slug instead of slugify(name)."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    project = make_gql_project(
        project_name="my project",
        org_name=ORG_NAME,
        teams=[make_team(name="default-team")],
        project_id="custom-slug-123",
    )

    orgs = _run_build_desired_state(integration, [project])

    assert isinstance(orgs[0].projects, list)
    assert orgs[0].projects[0].slug == "custom-slug-123"


def test_build_desired_state_event_throttle_rate_defaults_to_zero(
    mocker: MockerFixture,
) -> None:
    """When event_throttle_rate is None in GQL data, the GIProject gets rate=0."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    project = make_gql_project(
        project_name="no-throttle-project",
        org_name=ORG_NAME,
        teams=[make_team(name="default-team")],
        event_throttle_rate=None,
    )

    orgs = _run_build_desired_state(integration, [project])

    assert isinstance(orgs[0].projects, list)
    assert orgs[0].projects[0].event_throttle_rate == 0


def test_build_desired_state_deduplicates_teams(mocker: MockerFixture) -> None:
    """Two projects that share a team name produce only one team entry in the org."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    shared_team = make_team(
        name="Shared Team",
        roles=[make_role(org_name=ORG_NAME, role_str="admin", usernames=["alice"])],
    )
    project_a = make_gql_project(
        project_name="project-a",
        org_name=ORG_NAME,
        teams=[shared_team],
    )
    project_b = make_gql_project(
        project_name="project-b",
        org_name=ORG_NAME,
        teams=[shared_team],
    )

    orgs = _run_build_desired_state(integration, [project_a, project_b])

    assert len(orgs) == 1
    org = orgs[0]

    # The team should appear exactly once
    assert isinstance(org.teams, list)
    assert len(org.teams) == 1
    assert org.teams[0].name == "Shared Team"

    # Both projects reference the team slug
    team_slug = slugify("Shared Team")
    assert isinstance(org.projects, list)
    assert org.projects[0].teams == [team_slug]
    assert org.projects[1].teams == [team_slug]


def test_build_desired_state_multiple_orgs(mocker: MockerFixture) -> None:
    """Projects in different orgs produce separate GIOrganization entries."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    project_org1 = make_gql_project(
        project_name="project-org1",
        org_name="org-1",
        teams=[make_team(name="default-team")],
    )
    project_org2 = make_gql_project(
        project_name="project-org2",
        org_name="org-2",
        teams=[make_team(name="default-team")],
    )

    orgs = _run_build_desired_state(integration, [project_org1, project_org2])

    assert len(orgs) == 2
    org_names = {org.name for org in orgs}
    assert org_names == {"org-1", "org-2"}


def test_build_desired_state_raises_for_project_without_teams(
    mocker: MockerFixture,
) -> None:
    """A project with no teams raises ValueError immediately."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    project = make_gql_project(
        project_name="no-team-project",
        org_name=ORG_NAME,
        teams=[],
    )

    with pytest.raises(ValueError, match="has no teams assigned"):
        _run_build_desired_state(integration, [project])


def test_build_desired_state_org_users_deduplicated_across_teams(
    mocker: MockerFixture,
) -> None:
    """A user in two teams within the same org appears once in org.users."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    alice_role_team_a = make_role(
        org_name=ORG_NAME, role_str="admin", usernames=["alice"]
    )
    alice_role_team_b = make_role(
        org_name=ORG_NAME, role_str="member", usernames=["alice"]
    )
    team_a = make_team(name="Team A", roles=[alice_role_team_a])
    team_b = make_team(name="Team B", roles=[alice_role_team_b])

    project_a = make_gql_project(
        project_name="project-a",
        org_name=ORG_NAME,
        teams=[team_a],
    )
    project_b = make_gql_project(
        project_name="project-b",
        org_name=ORG_NAME,
        teams=[team_b],
    )

    orgs = _run_build_desired_state(integration, [project_a, project_b])

    org = orgs[0]
    assert isinstance(org.users, list)
    alice_entries = [u for u in org.users if u.email == f"alice@{MAIL_DOMAIN}"]
    assert len(alice_entries) == 1


def test_build_desired_state_highest_role_wins_across_teams(
    mocker: MockerFixture,
) -> None:
    """When a user appears in multiple teams with different org roles, the highest wins.

    This is deterministic regardless of project/team iteration order, unlike
    a first-team-wins approach which depends on GraphQL query ordering.
    """
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    alice_as_member = make_role(
        org_name=ORG_NAME, role_str="member", usernames=["alice"]
    )
    alice_as_admin = make_role(org_name=ORG_NAME, role_str="admin", usernames=["alice"])
    team_member = make_team(name="Team Member", roles=[alice_as_member])
    team_admin = make_team(name="Team Admin", roles=[alice_as_admin])

    # Project order: member team first, admin team second
    project_a = make_gql_project(
        project_name="project-a", org_name=ORG_NAME, teams=[team_member]
    )
    project_b = make_gql_project(
        project_name="project-b", org_name=ORG_NAME, teams=[team_admin]
    )

    orgs = _run_build_desired_state(integration, [project_a, project_b])

    org = orgs[0]
    assert isinstance(org.users, list)
    alice_entries = [u for u in org.users if u.email == f"alice@{MAIL_DOMAIN}"]
    assert len(alice_entries) == 1
    assert alice_entries[0].role == "admin"

    # Also verify order independence: admin team first, member team second
    orgs_reversed = _run_build_desired_state(integration, [project_b, project_a])
    org_reversed = orgs_reversed[0]
    assert isinstance(org_reversed.users, list)
    alice_reversed = [
        u for u in org_reversed.users if u.email == f"alice@{MAIL_DOMAIN}"
    ]
    assert len(alice_reversed) == 1
    assert alice_reversed[0].role == "admin"


def test_build_desired_state_empty_projects_list(mocker: MockerFixture) -> None:
    """An empty project list produces an empty GIOrganization list."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    orgs = _run_build_desired_state(integration, [])

    assert orgs == []


def test_build_desired_state_team_slug_used_in_project_teams(
    mocker: MockerFixture,
) -> None:
    """Team slugs (derived from team names) are correctly referenced in project teams list."""
    integration = make_integration()
    mocker.patch.object(integration, "_get_ldap_member_ids", return_value=[])

    team = make_team(name="My Backend Team")
    project = make_gql_project(
        project_name="svc",
        org_name=ORG_NAME,
        teams=[team],
    )

    orgs = _run_build_desired_state(integration, [project])

    assert isinstance(orgs[0].projects, list)
    gi_project = orgs[0].projects[0]
    assert gi_project.teams == ["my-backend-team"]


def test_build_desired_state_ldap_group_fetched_once_across_teams(
    mocker: MockerFixture,
) -> None:
    """A shared LDAP group referenced by multiple teams is fetched only once."""
    integration = make_integration()
    mock_get_ldap = mocker.patch.object(
        integration, "_get_ldap_member_ids", return_value=["shared-user"]
    )

    shared_group = "shared-ldap-group"
    team_a = make_team(name="Team A", ldap_groups=[shared_group])
    team_b = make_team(name="Team B", ldap_groups=[shared_group])

    project_a = make_gql_project(
        project_name="project-a", org_name=ORG_NAME, teams=[team_a]
    )
    project_b = make_gql_project(
        project_name="project-b", org_name=ORG_NAME, teams=[team_b]
    )

    orgs = _run_build_desired_state(integration, [project_a, project_b])

    # The group should be fetched exactly once despite appearing in two teams
    assert mock_get_ldap.call_count == 1
    assert mock_get_ldap.call_args.kwargs["group_name"] == shared_group

    # Both teams should still receive the members
    org = orgs[0]
    assert isinstance(org.teams, list)
    team_user_emails = {user.email for team in org.teams for user in (team.users or [])}
    assert f"shared-user@{MAIL_DOMAIN}" in team_user_emails
