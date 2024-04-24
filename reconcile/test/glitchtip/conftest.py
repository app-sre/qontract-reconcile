from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import pytest
from pytest_httpserver import HTTPServer
from pytest_mock import MockerFixture

from reconcile.test.fixtures import Fixtures
from reconcile.utils.glitchtip import GlitchtipClient
from reconcile.utils.internal_groups.client import InternalGroupsClient
from reconcile.utils.oc import OCNative
from reconcile.utils.oc_map import OCMap
from reconcile.utils.rest_api_base import BearerTokenAuth


@pytest.fixture
def glitchtip_url(httpserver: HTTPServer) -> str:
    return httpserver.url_for("")


@pytest.fixture
def glitchtip_token() -> str:
    return "1234567890"


@pytest.fixture
def glitchtip_client_minimal(
    glitchtip_url: str, glitchtip_token: str
) -> GlitchtipClient:
    return GlitchtipClient(host=glitchtip_url, auth=BearerTokenAuth(glitchtip_token))


@pytest.fixture
def glitchtip_client(
    glitchtip_client_minimal: GlitchtipClient,
    glitchtip_server_full_api_response: None,
) -> GlitchtipClient:
    return glitchtip_client_minimal


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("glitchtip")


@pytest.fixture
def glitchtip_server_full_api_response(
    set_httpserver_responses_based_on_fixture: Callable, fx: Fixtures
) -> None:
    """Text fixture.

    See reconcile/glitchtip/README.md for more details.
    """
    set_httpserver_responses_based_on_fixture(
        fx=fx,
        paths=[
            "/api/0/organizations/",
            "/api/0/organizations/esa/",
            "/api/0/organizations/esa/teams/",
            "/api/0/organizations/nasa/teams/",
            "/api/0/organizations/esa/projects/",
            "/api/0/organizations/nasa/projects/",
            "/api/0/organizations/esa/members/",
            "/api/0/organizations/nasa/members/",
            "/api/0/organizations/nasa/members/29/",
            "/api/0/organizations/nasa/members/29/teams/nasa-pilots/",
            "/api/0/projects/nasa/science-tools/teams/nasa-flight-control/",
            "/api/0/projects/nasa/science-tools/",
            "/api/0/teams/esa/esa-pilots/",
            "/api/0/teams/esa/esa-pilots/members/",
            "/api/0/teams/esa/esa-flight-control/members/",
            "/api/0/teams/nasa/nasa-pilots/members/",
            "/api/0/teams/nasa/nasa-pilots/projects/",
            "/api/0/teams/nasa/nasa-flight-control/members/",
            # glitchtip-project-dsn
            "/api/0/projects/nasa/apollo-11-flight-control/keys/",
            "/api/0/projects/empty-org/project-does-not-exist-yet/keys/",
            "/api/0/organizations/empty-org/projects/",
            # project-alerts
            "/api/0/projects/nasa/science-tools/alerts/",
            "/api/0/projects/nasa/science-tools/alerts/1/",
            "/api/0/projects/esa/rosetta-flight-control/alerts/",
            "/api/0/projects/esa/rosetta-spacecraft/alerts/",
            "/api/0/projects/nasa/apollo-11-flight-control/alerts/",
            "/api/0/projects/nasa/apollo-11-spacecraft/alerts/",
        ],
    )


@pytest.fixture
def fake_secret() -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "fake-secret"},
        "data": {
            "dsn": "fake",
            "security_endpoint": "fake",
        },
    }


@pytest.fixture
def oc(mocker: MockerFixture, fake_secret: dict[str, Any]) -> OCNative:
    oc = mocker.patch("reconcile.utils.oc.OCNative", autospec=True)
    oc.get_items.return_value = [fake_secret]
    return oc


@pytest.fixture
def oc_map(mocker: MockerFixture, oc: OCNative) -> OCMap:
    oc_map = mocker.patch("reconcile.utils.oc_map.OCMap", autospec=True)
    oc_map.get_cluster.return_value = oc
    return oc_map


@pytest.fixture
def internal_groups_client(mocker: MockerFixture) -> Mock:
    return mocker.create_autospec(spec=InternalGroupsClient)
