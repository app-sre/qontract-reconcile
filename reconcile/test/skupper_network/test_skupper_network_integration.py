import copy
from typing import Any

import pytest

from reconcile.gql_definitions.skupper_network.skupper_networks import SkupperNetworkV1
from reconcile.skupper_network import integration as intg
from reconcile.skupper_network.models import (
    Defaults,
    SkupperSite,
)
from reconcile.skupper_network.site_controller import CONFIG_NAME
from reconcile.test.fixtures import Fixtures
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory


@pytest.fixture
def cluster() -> str:
    return "cluster"


@pytest.fixture
def ns() -> str:
    return "namespace"


@pytest.fixture
def ri(cluster: str, ns: str) -> ResourceInventory:
    _ri = ResourceInventory()
    _ri.initialize_resource_type(
        cluster=cluster, namespace=ns, resource_type="ConfigMap"
    )
    return _ri


def or_factory(data: dict[str, Any]) -> OR:
    return OR(
        body=copy.deepcopy(data),
        integration="intg",
        integration_version="1",
    )


def test_skupper_network_intg_get_skupper_networks(
    skupper_networks: list[SkupperNetworkV1],
) -> None:
    assert len(skupper_networks) == 2
    assert skupper_networks[0].identifier == "small"
    assert len(skupper_networks[0].namespaces) == 2

    assert skupper_networks[1].identifier == "advanced"
    assert len(skupper_networks[1].namespaces) == 9


@pytest.mark.xfail(raises=intg.SkupperNetworkExcpetion, strict=True)
def test_skupper_network_intg_compile_skupper_sites_island(fx: Fixtures) -> None:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return fx.get_anymarkup("skupper_networks-island.yml")

    skupper_networks = intg.get_skupper_networks(q)
    intg.compile_skupper_sites(skupper_networks)


def test_skupper_network_intg_compile_skupper_sites(
    skupper_sites: list[SkupperSite],
) -> None:
    assert len(skupper_sites) == 10

    internal_1 = skupper_sites[0]
    private_1 = skupper_sites[2]
    delete_1 = skupper_sites[4]
    public_1 = skupper_sites[6]
    small_1 = skupper_sites[8]

    assert internal_1.delete is False
    assert internal_1.config.edge is True
    assert internal_1.config.router_memory_limit == "1Gi"
    assert internal_1.config.ingress == Defaults.DEFAULT_INGRESS
    assert internal_1.is_connected_to(public_1) is True

    assert private_1.delete is False
    assert private_1.config.edge is False
    assert private_1.config.router_memory_limit == "1Gi"
    assert private_1.config.ingress == Defaults.DEFAULT_INGRESS
    assert private_1.is_connected_to(public_1) is True

    assert delete_1.delete is True
    assert delete_1.config.edge is False
    assert delete_1.config.router_memory_limit == "1Gi"
    assert delete_1.config.ingress == Defaults.DEFAULT_INGRESS

    assert public_1.delete is False
    assert public_1.config.edge is False
    assert public_1.config.router_memory_limit == "1Gi"
    assert public_1.config.ingress == Defaults.DEFAULT_INGRESS
    # public_1 and small_1 are in different skupper networks
    assert public_1.is_connected_to(small_1) is False

    assert small_1.delete is False
    assert small_1.config.edge is False
    assert small_1.config.router_memory_limit == "1Gi"
    assert small_1.config.ingress == Defaults.DEFAULT_INGRESS
    # public_1 and small_1 are in different skupper networks
    assert small_1.is_connected_to(public_1) is False


def test_skupper_network_intg_fetch_desired_state(
    skupper_sites: list[SkupperSite],
) -> None:
    ri = ResourceInventory()
    integration_managed_kinds = intg.fetch_desired_state(
        ri=ri, skupper_sites=skupper_sites
    )
    assert integration_managed_kinds == {
        "Deployment",
        "ConfigMap",
        "Role",
        "RoleBinding",
        "ServiceAccount",
    }
    # test some random resources
    assert ri.get_desired("internal-1", "edge-1", "ConfigMap", CONFIG_NAME)
    assert ri.get_desired(
        "public-1", "public-1", "Deployment", "skupper-site-controller"
    )
    # deleted sites should not be present
    assert ri.get_desired("public-1", "delete-1", "ConfigMap", CONFIG_NAME) is None


def test_skupper_network_intg_fetch_current_state(
    oc_map: OC_Map,
    skupper_sites: list[SkupperSite],
    fake_site_configmap: dict[str, Any],
) -> None:
    ri = ResourceInventory()
    internal_1 = skupper_sites[0]
    intg.fetch_current_state(
        site=internal_1,
        oc_map=oc_map,
        ri=ri,
        integration_managed_kinds=["ConfigMap"],
    )
    assert (
        ri.get_current("internal-1", "edge-1", "ConfigMap", CONFIG_NAME).body
        == fake_site_configmap
    )


def test_skupper_network_intg_skupper_site_config_changes_no_changes(
    fake_site_configmap: dict[str, Any], ri: ResourceInventory, cluster: str, ns: str
) -> None:
    current = or_factory(fake_site_configmap)
    desired = or_factory(fake_site_configmap)
    ri.add_current(cluster, ns, "ConfigMap", current.name, current)
    ri.add_desired(cluster, ns, "ConfigMap", desired.name, desired)
    assert not intg.skupper_site_config_changes(ri)


def test_skupper_network_intg_skupper_site_config_changes_current_different(
    fake_site_configmap: dict[str, Any], ri: ResourceInventory, cluster: str, ns: str
) -> None:
    current = or_factory(fake_site_configmap)
    current.body["data"]["router-memory"] = "2Gi"
    desired = or_factory(fake_site_configmap)
    ri.add_current(cluster, ns, "ConfigMap", current.name, current)
    ri.add_desired(cluster, ns, "ConfigMap", desired.name, desired)
    assert intg.skupper_site_config_changes(ri)


def test_skupper_network_intg_skupper_site_config_changes_desired_different(
    fake_site_configmap: dict[str, Any], ri: ResourceInventory, cluster: str, ns: str
) -> None:
    current = or_factory(fake_site_configmap)
    desired = or_factory(fake_site_configmap)
    desired.body["data"]["router-memory"] = "2Gi"
    ri.add_current(cluster, ns, "ConfigMap", current.name, current)
    ri.add_desired(cluster, ns, "ConfigMap", desired.name, desired)
    assert intg.skupper_site_config_changes(ri)


def test_skupper_network_intg_skupper_site_config_changes_no_current(
    fake_site_configmap: dict[str, Any], ri: ResourceInventory, cluster: str, ns: str
) -> None:
    desired = or_factory(fake_site_configmap)
    ri.add_desired(cluster, ns, "ConfigMap", desired.name, desired)
    assert not intg.skupper_site_config_changes(ri)


def test_skupper_network_intg_skupper_site_config_changes_no_desired(
    fake_site_configmap: dict[str, Any], ri: ResourceInventory, cluster: str, ns: str
) -> None:
    current = or_factory(fake_site_configmap)
    ri.add_current(cluster, ns, "ConfigMap", current.name, current)
    assert not intg.skupper_site_config_changes(ri)
