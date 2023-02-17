from collections.abc import Callable
from typing import Optional

import pytest

from reconcile.gql_definitions.skupper_network.skupper_networks import (
    ClusterPeeringConnectionClusterRequesterV1,
    ClusterPeeringConnectionClusterRequesterV1_ClusterV1,
    ClusterPeeringV1,
    ClusterSpecV1,
    ClusterV1,
    NamespaceV1,
    SkupperSiteConfigDefaultsV1,
    SkupperSiteConfigV1,
)
from reconcile.skupper_network.models import (
    Defaults,
    SkupperConfig,
    SkupperSite,
)


@pytest.fixture
def network_config() -> SkupperSiteConfigDefaultsV1:
    """Network config fixture."""
    return SkupperSiteConfigDefaultsV1(
        clusterLocal=None,
        console=None,
        consoleAuthentication=None,
        consoleIngress=None,
        controllerCpuLimit=None,
        controllerCpu=None,
        controllerMemoryLimit=None,
        controllerMemory=None,
        controllerPodAntiaffinity=None,
        controllerServiceAnnotations=None,
        edge=None,
        ingress=None,
        routerConsole=None,
        routerCpuLimit=None,
        routerCpu=None,
        routerMemoryLimit=None,
        routerMemory=None,
        routerPodAntiaffinity=None,
        routerServiceAnnotations=None,
        routers=None,
        routerLogging=None,
        serviceController=None,
        serviceSync=None,
        skupperSiteController="quay.io/skupper/site-controller:1.2.0",
    )


@pytest.fixture
def site_config() -> SkupperSiteConfigV1:
    """Site config fixture."""
    return SkupperSiteConfigV1(
        clusterLocal=None,
        console=None,
        consoleAuthentication=None,
        consoleIngress=None,
        controllerCpuLimit=None,
        controllerCpu=None,
        controllerMemoryLimit=None,
        controllerMemory=None,
        controllerPodAntiaffinity=None,
        controllerServiceAnnotations=None,
        edge=None,
        ingress=None,
        routerConsole=None,
        routerCpuLimit=None,
        routerCpu=None,
        routerMemoryLimit=None,
        routerMemory=None,
        routerPodAntiaffinity=None,
        routerServiceAnnotations=None,
        routers=None,
        routerLogging=None,
        serviceController=None,
        serviceSync=None,
    )


SkupperSiteFactory = Callable[..., SkupperSite]
NamespaceFactory = Callable[..., NamespaceV1]


@pytest.fixture
def skupper_site_factory(
    network_config: SkupperSiteConfigDefaultsV1, site_config: SkupperSiteConfigV1
) -> SkupperSiteFactory:
    """Skupper site fixture."""

    def _skupper_site_factory(
        ns: NamespaceV1, edge: bool = False, delete: bool = False
    ) -> SkupperSite:
        site_config.edge = edge
        return SkupperSite(
            namespace=ns,
            skupper_site_controller="just-an-image",
            delete=delete,
            config=SkupperConfig.init(
                name=f"{ns.cluster.name}-{ns.name}",
                defaults=network_config,
                config=site_config,
            ),
        )

    return _skupper_site_factory


@pytest.fixture
def namespace_factory() -> NamespaceFactory:
    def _namespace_factory(
        name: str,
        private: bool,
        internal: bool = False,
        peered_with: Optional[str] = None,
    ) -> NamespaceV1:
        return NamespaceV1(
            name=name,
            clusterAdmin=None,
            cluster=ClusterV1(
                name=f"cluster-{name}",
                serverUrl="https://api.example.com:6443",
                insecureSkipTLSVerify=None,
                jumpHost=None,
                spec=ClusterSpecV1(private=private),
                automationToken=None,
                clusterAdminAutomationToken=None,
                internal=internal,
                disable=None,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionClusterRequesterV1(
                            provider="cluster-vpc-requester",
                            cluster=ClusterPeeringConnectionClusterRequesterV1_ClusterV1(
                                name=f"cluster-{peered_with}"
                            ),
                        )
                    ]
                )
                if peered_with
                else None,
            ),
            delete=False,
            skupperSite=None,
        )

    return _namespace_factory


def test_skupper_network_model_skupper_config_init(
    network_config: SkupperSiteConfigDefaultsV1, site_config: SkupperSiteConfigV1
) -> None:
    """Test SkupperConfig."""
    # network_config only
    network_config.console = False
    # site_config only
    site_config.router_cpu = "1000m"
    # network_config & site_config
    network_config.routers = 1
    site_config.routers = 2
    config = SkupperConfig.init(
        name="test", defaults=network_config, config=site_config
    )
    assert config.name == "test"
    # from network_config
    assert config.console is False
    # from site_config
    assert config.router_cpu == "1000m"
    # from site_config
    assert config.routers == 2
    # from defaults
    assert config.ingress == Defaults.DEFAULT_INGRESS
    assert (
        config.router_service_annotations == Defaults.DEFAULT_ROUTER_SERVICE_ANNOTATIONS
    )


def test_skupper_network_model_skupper_config_as_configmap(
    network_config: SkupperSiteConfigDefaultsV1, site_config: SkupperSiteConfigV1
) -> None:
    network_config.console = False
    site_config.router_cpu = "1000m"
    config = SkupperConfig.init(
        name="test", defaults=network_config, config=site_config
    )
    data = config.as_configmap_data()
    # test some values and underscored keys are converted to hyphenated)
    assert data["console"] == "false"
    assert data["router-cpu"] == "1000m"
    assert data["name"] == "test"
    assert data["router-logging"] == Defaults.DEFAULT_ROUTER_LOGGING


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
