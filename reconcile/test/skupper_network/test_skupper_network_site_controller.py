from typing import Any

import pytest

from reconcile.skupper_network.models import SkupperSite
from reconcile.skupper_network.site_controller import (
    SiteController,
    get_site_controller,
)


@pytest.fixture
def site(skupper_sites: list[SkupperSite]) -> SkupperSite:
    # edge-1 site
    return skupper_sites[0]


@pytest.fixture
def sc(site: SkupperSite) -> SiteController:
    return SiteController(site)


def test_skupper_network_site_controller_get_site_controller(site: SkupperSite) -> None:
    assert isinstance(get_site_controller(site), SiteController)


@pytest.mark.parametrize(
    "secret, expected",
    [
        ({}, False),
        ({"kind": "Not-A-secret"}, False),
        ({"kind": "Secret"}, False),
        ({"kind": "Secret", "metadata": {}}, False),
        ({"kind": "Secret", "metadata": {"labels": {}}}, False),
        ({"kind": "Secret", "metadata": {"labels": {"what": "ever"}}}, False),
        (
            {
                "kind": "Secret",
                "metadata": {"labels": {"skupper.io/type": "connection-token-request"}},
            },
            False,
        ),
        (
            {
                "kind": "Secret",
                "metadata": {"labels": SiteController.CONNECTION_TOKEN_LABELS},
            },
            True,
        ),
        (
            {
                "kind": "Secret",
                "metadata": {
                    "labels": {
                        **SiteController.CONNECTION_TOKEN_LABELS,
                        "just-another": "label",
                    }
                },
            },
            True,
        ),
    ],
)
def test_skupper_network_site_controller_is_usable_connection_token(
    sc: SiteController, secret: dict[str, Any], expected: bool
) -> None:
    assert sc.is_usable_connection_token(secret) == expected


def test_skupper_network_site_controller_v1_site_token(sc: SiteController) -> None:
    resource = sc.site_token("name", {"foo": "bar"})
    assert resource["metadata"]["name"] == "name"
    for i in {"foo": "bar"}.items():
        assert i in resource["metadata"]["labels"].items()
    assert (
        resource["metadata"]["labels"]["skupper.io/type"] == "connection-token-request"
    )
