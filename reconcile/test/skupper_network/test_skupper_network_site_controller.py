from typing import Any

import pytest

from reconcile.skupper_network.models import SkupperSite
from reconcile.skupper_network.site_controller import (
    CONFIG_NAME,
    LABELS,
    SiteController,
    SiteControllerV1,
    get_site_controller,
)


@pytest.fixture
def site(skupper_sites: list[SkupperSite]) -> SkupperSite:
    # edge-1 site
    return skupper_sites[0]


@pytest.fixture
def sc(site: SkupperSite) -> SiteController:
    return SiteController(site)


@pytest.fixture
def sc_v1(site: SkupperSite) -> SiteControllerV1:
    return SiteControllerV1(site)


@pytest.mark.parametrize(
    "image",
    [
        "registry/owner/image:1.0",
        "registry/owner/image:1.2",
        "registry/owner/image:1.1000",
        pytest.param(
            "registry/owner/image:2",
            marks=pytest.mark.xfail(strict=True, raises=NotImplementedError),
        ),
    ],
)
def test_skupper_network_site_controller_get_site_controller(
    image: str, site: SkupperSite
) -> None:
    site.skupper_site_controller = image
    assert isinstance(get_site_controller(site), SiteControllerV1)


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
    for i in LABELS.items():
        assert i in resource["metadata"]["labels"].items()
    assert (
        resource["metadata"]["labels"]["skupper.io/type"] == "connection-token-request"
    )


def test_skupper_network_site_controller_v1_site_config(
    sc_v1: SiteControllerV1, site: SkupperSite
) -> None:
    resource = sc_v1.site_config()
    assert resource["metadata"]["name"] == CONFIG_NAME
    assert resource["metadata"]["labels"] == LABELS
    # some some random data from the site config
    assert resource["data"]["name"] == site.name
    assert resource["data"]["edge"] == "true"
    # one value with hyphens
    assert resource["data"]["router-memory-limit"] == "1Gi"


def test_skupper_network_site_controller_v1_site_controller_deployment(
    sc_v1: SiteControllerV1, site: SkupperSite
) -> None:
    resource = sc_v1.site_controller_deployment()
    assert resource["metadata"]["name"] == "skupper-site-controller"
    assert resource["metadata"]["labels"] == LABELS
    assert resource["spec"]["replicas"] == 1
    assert (
        resource["spec"]["template"]["spec"]["containers"][0]["image"]
        == site.skupper_site_controller
    )


def test_skupper_network_site_controller_v1_site_controller_service_account(
    sc_v1: SiteControllerV1,
) -> None:
    resource = sc_v1.site_controller_service_account()
    assert resource["metadata"]["name"] == "skupper-site-controller"
    assert resource["metadata"]["labels"] == LABELS


def test_skupper_network_site_controller_v1_site_controller_role(
    sc_v1: SiteControllerV1,
) -> None:
    resource = sc_v1.site_controller_role()
    assert resource["metadata"]["name"] == "skupper-site-controller"
    assert resource["metadata"]["labels"] == LABELS
    # it doesn't matter what the rules are, just that there are some
    assert len(resource["rules"]) > 0


def test_skupper_network_site_controller_v1_site_controller_role_binding(
    sc_v1: SiteControllerV1,
) -> None:
    resource = sc_v1.site_controller_role_binding()
    assert resource["metadata"]["name"] == "skupper-site-controller"
    assert resource["metadata"]["labels"] == LABELS
    assert resource["roleRef"]["name"] == "skupper-site-controller"
    assert resource["subjects"][0]["name"] == "skupper-site-controller"
