from pathlib import Path
from typing import Any

import httpretty as httpretty_module
import pytest
from pytest_mock import MockerFixture

from reconcile.test.fixtures import Fixtures
from reconcile.utils.glitchtip import GlitchtipClient
from reconcile.utils.oc import OCNative
from reconcile.utils.oc_map import OCMap


@pytest.fixture
def glitchtip_url() -> str:
    return "http://fake-glitchtip-server.com"


@pytest.fixture
def glitchtip_token() -> str:
    return "1234567890"


@pytest.fixture
def glitchtip_client_minimal(
    glitchtip_url: str, glitchtip_token: str
) -> GlitchtipClient:
    return GlitchtipClient(host=glitchtip_url, token=glitchtip_token)


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
    httpretty: httpretty_module, glitchtip_url: str, fx: Fixtures
) -> None:
    """Text fixture.

    See reconcile/glitchtip/README.md for more details.
    """
    for path in [
        "api/0/organizations/",
        "api/0/organizations/esa/",
        "api/0/organizations/esa/teams/",
        "api/0/organizations/nasa/teams/",
        "api/0/organizations/esa/projects/",
        "api/0/organizations/nasa/projects/",
        "api/0/organizations/esa/members/",
        "api/0/organizations/nasa/members/",
        "api/0/organizations/nasa/members/29/",
        "api/0/organizations/nasa/members/29/teams/nasa-pilots/",
        "api/0/projects/nasa/science-tools/teams/nasa-flight-control/",
        "api/0/projects/nasa/science-tools/",
        "api/0/teams/esa/esa-pilots/",
        "api/0/teams/esa/esa-pilots/members/",
        "api/0/teams/esa/esa-flight-control/members/",
        "api/0/teams/nasa/nasa-pilots/members/",
        "api/0/teams/nasa/nasa-pilots/projects/",
        "api/0/teams/nasa/nasa-flight-control/members/",
        # glitchtip-project-dsn
        "api/0/projects/nasa/apollo-11-flight-control/keys/",
        "api/0/organizations/empty-org/projects/",
    ]:
        get_file = Path(fx.path(path)) / "get.json"
        if get_file.exists():
            httpretty.register_uri(
                httpretty.GET,
                f"{glitchtip_url}/{path}",
                body=get_file.read_text(),
                content_type="text/json",
            )
        post_file = Path(fx.path(path)) / "post.json"
        if post_file.exists():
            httpretty.register_uri(
                httpretty.POST,
                f"{glitchtip_url}/{path}",
                body=post_file.read_text(),
                content_type="text/json",
            )
        put_file = Path(fx.path(path)) / "put.json"
        if put_file.exists():
            httpretty.register_uri(
                httpretty.PUT,
                f"{glitchtip_url}/{path}",
                body=put_file.read_text(),
                content_type="text/json",
            )
        delete_file = Path(fx.path(path)) / "delete.json"
        if delete_file.exists():
            httpretty.register_uri(
                httpretty.DELETE,
                f"{glitchtip_url}/{path}",
                body=delete_file.read_text(),
                content_type="text/json",
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
