from collections.abc import (
    Callable,
    MutableMapping,
)
from typing import Optional

import pytest
from pyparsing import Any

from reconcile.gql_definitions.skupper_network.skupper_networks import NamespaceV1
from reconcile.skupper_network.models import SkupperSite

SkupperSiteFactory = Callable[..., SkupperSite]
NamespaceFactory = Callable[..., NamespaceV1]


@pytest.fixture
def skupper_site_factory() -> SkupperSiteFactory:
    """Skupper site fixture."""

    def _skupper_site_factory(
        ns: NamespaceV1, edge: bool = False, delete: bool = False
    ) -> SkupperSite:
        site_config = {
            "kind": "ConfigMap",
            "metadata": {"name": "skupper-site"},
            "data": {"edge": "true" if edge else "false"},
        }
        return SkupperSite(
            name=f"{ns.cluster.name}-{ns.name}",
            site_controller_objects=[site_config],
            namespace=ns,
            delete=delete,
        )

    return _skupper_site_factory


@pytest.fixture
def namespace_factory(
    gql_class_factory: Callable[
        [type[NamespaceV1], MutableMapping[str, Any]],
        NamespaceV1,
    ]
) -> NamespaceFactory:
    def _namespace_factory(
        name: str,
        private: bool,
        internal: bool = False,
        peered_with: Optional[str] = None,
    ) -> NamespaceV1:
        return gql_class_factory(
            NamespaceV1,
            {
                "name": name,
                "cluster": {
                    "name": f"cluster-{name}",
                    "serverUrl": "https://api.example.com:6443",
                    "spec": {"private": private},
                    "internal": internal,
                    "peering": {
                        "connections": [
                            {
                                "provider": "cluster-vpc-requester",
                                "cluster": {"name": f"cluster-{peered_with}"},
                            }
                        ]
                    }
                    if peered_with
                    else None,
                },
                "delete": False,
            },
        )

    return _namespace_factory


def test_skupper_network_model_skupper_site_compute_connected_sites(
    skupper_site_factory: SkupperSiteFactory, namespace_factory: NamespaceFactory
) -> None:
    public01 = skupper_site_factory(
        namespace_factory("public01", private=False), edge=False
    )
    public02 = skupper_site_factory(
        namespace_factory("public02", private=False), edge=False
    )
    delete01 = skupper_site_factory(
        namespace_factory("delete01", private=False),
        edge=False,
        delete=True,
    )
    private01 = skupper_site_factory(
        namespace_factory("private01", private=True), edge=False
    )
    private02 = skupper_site_factory(
        namespace_factory("private02", private=True, peered_with="private01"),
        edge=False,
    )
    private03 = skupper_site_factory(
        namespace_factory("private03", private=True), edge=False
    )
    edge01 = skupper_site_factory(namespace_factory("edge01", private=False), edge=True)
    edge02 = skupper_site_factory(namespace_factory("edge02", private=False), edge=True)
    internal01 = skupper_site_factory(
        namespace_factory("internal01", private=True, internal=True), edge=False
    )
    internal02 = skupper_site_factory(
        namespace_factory("internal02", private=True, internal=True), edge=False
    )
    island01 = skupper_site_factory(
        namespace_factory("island01", private=False), edge=False
    )
    all_sites = [
        public01,
        public02,
        delete01,
        private01,
        private02,
        private03,
        edge01,
        edge02,
        internal01,
        internal02,
    ]
    for site in sorted(all_sites, reverse=True):
        site.compute_connected_sites(all_sites)

    assert public01.connected_sites == set()
    assert public01.has_incoming_connections(all_sites)
    assert public02.connected_sites == {public01}
    assert public02.is_connected_to(public01) is True
    assert private01.connected_sites == {public01, public02}
    assert private01.is_connected_to(public01) is True
    assert private01.is_connected_to(public02) is True
    assert private02.connected_sites == {public01, public02, private01}
    assert private02.has_incoming_connections(all_sites) is False
    assert private03.connected_sites == {public01, public02}
    assert private03.is_connected_to(private01) is False
    assert edge01.connected_sites == {public01, public02}
    assert edge01.has_incoming_connections(all_sites) is False
    assert edge02.connected_sites == {public01, public02}
    assert delete01.connected_sites == set()
    assert delete01.has_incoming_connections(all_sites) is False
    assert island01.is_island(all_sites) is True
    assert internal01.connected_sites == {public01, public02}
    assert internal01.has_incoming_connections([internal02])
    assert internal02.connected_sites == {public01, public02, internal01}
    assert internal02.has_incoming_connections(all_sites) is False


def test_skupper_network_model_skupper_site_properties(
    skupper_site_factory: SkupperSiteFactory, namespace_factory: NamespaceFactory
) -> None:
    public01 = skupper_site_factory(
        namespace_factory("public01", private=False), edge=False
    )
    assert public01.on_private_cluster is False
    assert public01.on_public_cluster is True
    assert public01.name == "cluster-public01-public01"
    assert public01.cluster.name == "cluster-public01"
    assert public01.is_edge_site is False
    assert public01.token_labels

    private01 = skupper_site_factory(
        namespace_factory("private01", private=True), edge=False
    )

    assert private01.on_private_cluster is True
    assert private01.on_public_cluster is False
    assert private01.name == "cluster-private01-private01"
    assert private01.cluster.name == "cluster-private01"
    assert private01.is_edge_site is False
    assert private01.unique_token_name(public01)
    assert private01.token_name(public01) == "cluster-public01-public01"

    private02 = skupper_site_factory(
        namespace_factory("private02", private=True, peered_with="private01"),
        edge=False,
    )
    assert private02.is_peered_with(private01) is True

    internal01 = skupper_site_factory(
        namespace_factory("internal01", private=False), edge=True
    )
    assert internal01.is_edge_site is True


def test_skupper_network_model_skupper_site_token_labels(
    skupper_site_factory: SkupperSiteFactory, namespace_factory: NamespaceFactory
) -> None:
    # very long name
    long01 = skupper_site_factory(
        namespace_factory(
            "this-is-a-very-long-namespace-name-and-clearly-exceeds-some-kubernetes-limits",
            private=False,
        ),
        edge=False,
    )
    # https://issues.redhat.com/browse/APPSRE-6993
    assert (
        long01.token_labels["token-receiver"]
        == "cluster-this-is-a-very-long-namespace-name-and-clearly-exceeds-"
    )
    assert len(long01.token_labels["token-receiver"]) <= 63
