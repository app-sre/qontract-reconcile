from reconcile.glitchtip.integration import fetch_current_state
from reconcile.utils.glitchtip import GlitchtipClient, Organization


def test_fetch_current_state(
    glitchtip_client: GlitchtipClient, glitchtip_server_full_api_response, fx
):
    current_state = fetch_current_state(
        glitchtip_client, ignore_users=["sd-app-sre+glitchtip@redhat.com"]
    )
    # sort everything for easier comparison
    for org in current_state:
        for proj in org.projects:
            proj.teams.sort()
        org.projects.sort()
        for team in org.teams:
            team.users.sort()
        org.teams.sort()
        org.users.sort()
    current_state.sort()

    expected_current_state = [
        Organization(**i) for i in fx.get_anymarkup("current_state.yml")
    ]
    # sort everything for easier comparison
    for org in expected_current_state:
        for proj in org.projects:
            proj.teams.sort()
        org.projects.sort()
        for team in org.teams:
            team.users.sort()
        org.teams.sort()
        org.users.sort()
    expected_current_state.sort()
    assert current_state == expected_current_state
