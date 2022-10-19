from github import UnknownObjectException
from reconcile.glitchtip.integration import fetch_current_state, fetch_desired_state
from reconcile.utils.glitchtip import GlitchtipClient, Organization
from reconcile.gql_definitions.glitchtip.glitchtip_project import GlitchtipProjectsV1


def sort_all(orgs: list[Organization]) -> list[Organization]:
    """sort everything for easier comparison"""
    for org in orgs:
        for proj in org.projects:
            proj.teams.sort()
            for team in proj.teams:
                team.users.sort()
        org.projects.sort()
        for team in org.teams:
            team.users.sort()
        org.teams.sort()
        org.users.sort()
    orgs.sort()
    return orgs


def test_fetch_current_state(
    glitchtip_client: GlitchtipClient, glitchtip_server_full_api_response, fx
):
    current_state = fetch_current_state(
        glitchtip_client, ignore_users=["sd-app-sre+glitchtip@nasa.com"]
    )
    expected_current_state = [
        Organization(**i) for i in fx.get_anymarkup("current_state_expected.yml")
    ]

    assert sort_all(current_state) == sort_all(expected_current_state)


def test_desire_state(mocker, fx):
    gh = mocker.patch("github.Github")
    gh.get_user.side_effect = UnknownObjectException(status=404, data="", headers={})
    projects = [
        GlitchtipProjectsV1(**i) for i in fx.get_anymarkup("desire_state_projects.yml")
    ]
    desired_state = fetch_desired_state(
        glitchtip_projects=projects, gh=gh, mail_address="nasa.com"
    )
    expected_desire_state = [
        Organization(**i) for i in fx.get_anymarkup("desire_state_expected.yml")
    ]
    assert sort_all(desired_state)[1] == sort_all(expected_desire_state)[1]
