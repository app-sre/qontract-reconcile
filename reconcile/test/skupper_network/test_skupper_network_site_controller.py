from typing import Any

import pytest

from reconcile.skupper_network import site_controller
from reconcile.skupper_network.models import SkupperSite


@pytest.fixture
def site(skupper_sites: list[SkupperSite]) -> SkupperSite:
    # edge-1 site
    return skupper_sites[0]


def test_skupper_network_site_controller_site_config(site: SkupperSite) -> None:
    resource = site_controller.site_config(site)
    assert resource["metadata"]["name"] == site_controller.CONFIG_NAME
    assert resource["metadata"]["labels"] == site_controller.LABELS
    # some some random data from the site config
    assert resource["data"]["name"] == site.name
    assert resource["data"]["edge"] == "true"
    # one value with hyphens
    assert resource["data"]["router-memory-limit"] == "1Gi"


def test_skupper_network_site_controller_site_token() -> None:
    resource = site_controller.site_token("name", {"foo": "bar"})
    assert resource["metadata"]["name"] == "name"
    for i in {"foo": "bar"}.items():
        assert i in resource["metadata"]["labels"].items()
    for i in site_controller.LABELS.items():
        assert i in resource["metadata"]["labels"].items()
    assert (
        resource["metadata"]["labels"]["skupper.io/type"] == "connection-token-request"
    )


def test_skupper_network_site_controller_site_controller_deployment(
    site: SkupperSite,
) -> None:
    resource = site_controller.site_controller_deployment(site)
    assert resource["metadata"]["name"] == "skupper-site-controller"
    assert resource["metadata"]["labels"] == site_controller.LABELS
    assert resource["spec"]["replicas"] == 1
    assert (
        resource["spec"]["template"]["spec"]["containers"][0]["image"]
        == site.skupper_site_controller
    )


def test_skupper_network_site_controller_site_controller_service_account(
    site: SkupperSite,
) -> None:
    resource = site_controller.site_controller_service_account(site)
    assert resource["metadata"]["name"] == "skupper-site-controller"
    assert resource["metadata"]["labels"] == site_controller.LABELS


def test_skupper_network_site_controller_site_controller_role(
    site: SkupperSite,
) -> None:
    resource = site_controller.site_controller_role(site)
    assert resource["metadata"]["name"] == "skupper-site-controller"
    assert resource["metadata"]["labels"] == site_controller.LABELS
    # it doesn't matter what the rules are, just that there are some
    assert len(resource["rules"]) > 0


def test_skupper_network_site_controller_site_controller_role_binding(
    site: SkupperSite,
) -> None:
    resource = site_controller.site_controller_role_binding(site)
    assert resource["metadata"]["name"] == "skupper-site-controller"
    assert resource["metadata"]["labels"] == site_controller.LABELS
    assert resource["roleRef"]["name"] == "skupper-site-controller"
    assert resource["subjects"][0]["name"] == "skupper-site-controller"


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
                "metadata": {"labels": site_controller.CONNECTION_TOKEN_LABELS},
            },
            True,
        ),
        (
            {
                "kind": "Secret",
                "metadata": {
                    "labels": {
                        **site_controller.CONNECTION_TOKEN_LABELS,
                        "just-another": "label",
                    }
                },
            },
            True,
        ),
    ],
)
def test_skupper_network_site_controller_is_usable_connection_token(
    secret: dict[str, Any], expected: bool
) -> None:
    assert site_controller.is_usable_connection_token(secret) == expected
