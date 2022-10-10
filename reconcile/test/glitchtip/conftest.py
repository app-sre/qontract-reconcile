import httpretty as httpretty_module
import pytest
from reconcile.test.fixtures import Fixtures
from reconcile.utils.glitchtip import GlitchtipClient


@pytest.fixture
def glitchtip_url() -> str:
    return "http://fake-glitchtip-server.com"


@pytest.fixture
def glitchtip_token() -> str:
    return "1234567890"


@pytest.fixture
def glitchtip_client(glitchtip_url, glitchtip_token) -> GlitchtipClient:
    return GlitchtipClient(host=glitchtip_url, token=glitchtip_token)


@pytest.fixture
def fx():
    return Fixtures("glitchtip")


@pytest.fixture
def glitchtip_server_full_api_response(
    httpretty: httpretty_module, glitchtip_url: str, fx: Fixtures
):
    """Text fixture.

    See reconcile/glitchtip/README.md for more details.
    """
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/organizations",
        body=fx.get("organizations.json"),
        content_type="text/json",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/organizations/esa/teams/",
        body=fx.get("esa_teams.json"),
        content_type="text/json",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/organizations/nasa/teams/",
        body=fx.get("nasa_teams.json"),
        content_type="text/json",
    )

    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/organizations/esa/projects/",
        body=fx.get("esa_projects.json"),
        content_type="text/json",
    )

    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/organizations/nasa/projects/",
        body=fx.get("nasa_projects.json"),
        content_type="text/json",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/organizations/esa/members/",
        body=fx.get("esa_members.json"),
        content_type="text/json",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/organizations/nasa/members/",
        body=fx.get("nasa_members.json"),
        content_type="text/json",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/teams/esa/esa-pilots/members/",
        body=fx.get("esa_team_members_esa-pilots.json"),
        content_type="text/json",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/teams/esa/esa-flight-control/members/",
        body=fx.get("esa_team_members_esa-flight-control.json"),
        content_type="text/json",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/teams/nasa/nasa-pilots/members/",
        body=fx.get("nasa_team_members_nasa-pilots.json"),
        content_type="text/json",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{glitchtip_url}/api/0/teams/nasa/nasa-flight-control/members/",
        body=fx.get("nasa_team_members_nasa-flight-control.json"),
        content_type="text/json",
    )
