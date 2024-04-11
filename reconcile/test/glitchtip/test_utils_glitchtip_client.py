from reconcile.utils.glitchtip import (
    GlitchtipClient,
    Organization,
    Project,
    Team,
    User,
)
from reconcile.utils.glitchtip.models import (
    ProjectAlert,
    ProjectAlertRecipient,
    ProjectKey,
    RecipientType,
)


def test_glitchtip_organizations(glitchtip_client: GlitchtipClient) -> None:
    assert glitchtip_client.organizations() == [
        Organization(id=10, name="ESA", slug="esa", projects=[], teams=[], users=[]),
        Organization(id=4, name="NASA", slug="nasa", projects=[], teams=[], users=[]),
    ]


def test_glitchtip_create_organization(glitchtip_client: GlitchtipClient) -> None:
    org = glitchtip_client.create_organization(name="ASA")
    assert org.name == "ASA"
    assert org.slug == "asa"


def test_glitchtip_delete_organization(glitchtip_client: GlitchtipClient) -> None:
    glitchtip_client.delete_organization(slug="esa")


def test_glitchtip_teams(glitchtip_client: GlitchtipClient) -> None:
    assert glitchtip_client.teams(organization_slug="nasa") == [
        Team(id=4, slug="nasa-flight-control", users=[]),
        Team(id=2, slug="nasa-pilots", users=[]),
    ]


def test_glitchtip_create_team(glitchtip_client: GlitchtipClient) -> None:
    team = glitchtip_client.create_team(organization_slug="esa", slug="launchpad-crew")
    assert team.slug == "launchpad-crew"


def test_glitchtip_delete_team(glitchtip_client: GlitchtipClient) -> None:
    glitchtip_client.delete_team(organization_slug="esa", slug="esa-pilots")


def test_glitchtip_projects(glitchtip_client: GlitchtipClient) -> None:
    assert glitchtip_client.projects(organization_slug="nasa") == [
        Project(
            id=8,
            name="apollo-11-flight-control",
            slug="apollo-11-flight-control",
            platform="python",
            teams=[Team(id=4, slug="nasa-flight-control", users=[])],
        ),
        Project(
            id=7,
            name="apollo-11-spacecraft",
            slug="apollo-11-spacecraft",
            platform="python",
            teams=[
                Team(id=2, slug="nasa-pilots", users=[]),
                Team(id=4, slug="nasa-flight-control", users=[]),
            ],
        ),
    ]


def test_glitchtip_project_key(glitchtip_client: GlitchtipClient) -> None:
    assert glitchtip_client.project_key(
        organization_slug="nasa", project_slug="apollo-11-flight-control"
    ) == ProjectKey(
        dsn="http://public_dsn", security_endpoint="http://security_endpoint"
    )


def test_glitchtip_create_project(glitchtip_client: GlitchtipClient) -> None:
    project = glitchtip_client.create_project(
        organization_slug="nasa",
        team_slug="nasa-pilots",
        name="science-tools",
        platform="python",
    )
    assert project.pk == 13
    assert project.slug == "science-tools"
    assert project.teams[0].pk == 2


def test_glitchtip_update_project(glitchtip_client: GlitchtipClient) -> None:
    project = glitchtip_client.update_project(
        organization_slug="nasa",
        slug="science-tools",
        name="science-tools-advanced",
        platform="python",
        event_throttle_rate=0,
    )
    assert project.pk == 11
    assert project.slug == "science-tools"
    assert project.name == "science-tools-advanced"


def test_glitchtip_delete_project(glitchtip_client: GlitchtipClient) -> None:
    glitchtip_client.delete_project(organization_slug="nasa", slug="science-tools")


def test_glitchtip_project_alerts(glitchtip_client: GlitchtipClient) -> None:
    assert glitchtip_client.project_alerts(
        organization_slug="nasa", project_slug="science-tools"
    ) == [
        ProjectAlert(
            pk=14,
            name="alert-2",
            timespan_minutes=2000,
            quantity=1000,
            recipients=[
                ProjectAlertRecipient(
                    pk=20,
                    recipient_type=RecipientType.WEBHOOK,
                    url="https://example.com",
                )
            ],
        ),
        ProjectAlert(
            pk=7,
            name="alert-1",
            timespan_minutes=1000,
            quantity=1000,
            recipients=[
                ProjectAlertRecipient(pk=8, recipient_type=RecipientType.EMAIL, url="")
            ],
        ),
    ]


def test_glitchtip_create_project_alert(glitchtip_client: GlitchtipClient) -> None:
    alert = glitchtip_client.create_project_alert(
        organization_slug="nasa",
        project_slug="science-tools",
        alert=ProjectAlert(name="test", timespan_minutes=1, quantity=1),
    )
    assert alert.pk == 1


def test_glitchtip_update_project_alert(glitchtip_client: GlitchtipClient) -> None:
    alert = glitchtip_client.update_project_alert(
        organization_slug="nasa",
        project_slug="science-tools",
        alert=ProjectAlert(pk=1, name="foobar", timespan_minutes=1, quantity=1),
    )
    assert alert.pk == 1
    assert alert.name == "foobar"


def test_glitchtip_delete_project_alert(glitchtip_client: GlitchtipClient) -> None:
    glitchtip_client.delete_project_alert(
        organization_slug="nasa", project_slug="science-tools", alert_pk=1
    )


def test_glitchtip_add_project_to_team(glitchtip_client: GlitchtipClient) -> None:
    project = glitchtip_client.add_project_to_team(
        organization_slug="nasa", team_slug="nasa-flight-control", slug="science-tools"
    )
    assert len(project.teams) == 2


def test_glitchtip_remove_project_from_team(glitchtip_client: GlitchtipClient) -> None:
    glitchtip_client.remove_project_from_team(
        organization_slug="nasa", team_slug="nasa-flight-control", slug="science-tools"
    )


def test_glitchtip_organization_users(glitchtip_client: GlitchtipClient) -> None:
    assert glitchtip_client.organization_users(organization_slug="nasa") == [
        User(id=23, email="MichaelCollins@nasa.com", role="member", pending=False),
        User(
            id=22,
            email="GlobalFlightDirector@nasa.com",
            role="owner",
            pending=True,
        ),
        User(id=21, email="BuzzAldrin@nasa.com", role="member", pending=True),
        User(id=20, email="NeilArmstrong@nasa.com", role="member", pending=False),
        User(id=5, email="sd-app-sre+glitchtip@nasa.com", role="owner", pending=False),
    ]


def test_glitchtip_invite_user(glitchtip_client: GlitchtipClient) -> None:
    user = glitchtip_client.invite_user(
        organization_slug="nasa", email="Gene.Kranz@nasa.com", role="member"
    )
    assert user.email == "Gene.Kranz@nasa.com"
    assert user.pending


def test_glitchtip_delete_user(glitchtip_client: GlitchtipClient) -> None:
    glitchtip_client.delete_user(organization_slug="nasa", pk=29)


def test_glitchtip_update_user_role(glitchtip_client: GlitchtipClient) -> None:
    user = glitchtip_client.update_user_role(
        organization_slug="nasa", role="manager", pk=29
    )
    assert user.role == "manager"


def test_glitchtip_team_users(glitchtip_client: GlitchtipClient) -> None:
    assert glitchtip_client.team_users(
        organization_slug="nasa", team_slug="nasa-flight-control"
    ) == [
        User(id=23, email="MichaelCollins@nasa.com", role="member", pending=False),
        User(
            id=22,
            email="GlobalFlightDirector@nasa.com",
            role="owner",
            pending=True,
        ),
    ]


def test_glitchtip_add_user_to_team(glitchtip_client: GlitchtipClient) -> None:
    team = glitchtip_client.add_user_to_team(
        organization_slug="nasa", team_slug="nasa-pilots", user_pk=29
    )
    assert len(team.users) > 0


def test_glitchtip_remove_user_from_team(glitchtip_client: GlitchtipClient) -> None:
    glitchtip_client.remove_user_from_team(
        organization_slug="nasa", team_slug="nasa-pilots", user_pk=29
    )
