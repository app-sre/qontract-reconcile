from typing import Any, cast
from unittest.mock import Mock
import pytest
from reconcile.openshift_base import CurrentStateSpec
from reconcile.test.fixtures import Fixtures

from reconcile import openshift_resources_base as orb
from reconcile.openshift_resources_base import canonicalize_namespaces, ob
from reconcile.utils import oc
from reconcile.utils.openshift_resource import ResourceInventory


fxt = Fixtures("namespaces")


@pytest.fixture
def namespaces() -> list[dict[str, Any]]:
    return [fxt.get_anymarkup("openshift-resources-only.yml")]


@pytest.fixture
def oc_cs1() -> oc.OCClient:
    client = cast(
        oc.OCNative, oc.OC(cluster_name="cs1", server="", token="", local=True)
    )
    client.init_api_resources = True
    client.api_kind_version = {
        "Template": ["template.openshift.io/v1"],
        "Subscription": ["apps.open-cluster-management.io/v1", "operators.coreos.com"],
    }
    client.api_resources = client.api_kind_version.keys()
    client.get_items = lambda kind, **kwargs: []
    return client


@pytest.fixture
def tmpl1() -> dict[str, Any]:
    return {
        "kind": "Template",
        "apiVersion": "template.openshift.io/v1",
        "metadata": {"name": "tmpl1"},
    }


@pytest.fixture
def current_state_spec(oc_cs1: oc.OCClient) -> CurrentStateSpec:
    return CurrentStateSpec(
        oc=oc_cs1, cluster="cs1", namespace="ns1", kind="Template", resource_names=None
    )


def test_secret(namespaces: list[dict[str, Any]], mocker):
    mocker.patch.object(ob, "aggregate_shared_resources", autospec=True)
    expected = (
        [
            {
                "name": "ns1",
                "cluster": {"name": "cs1"},
                "managedResourceTypes": ["Template"],
                "openshiftResources": [
                    {
                        "provider": "vault-secret",
                        "path": "/secret/place.yml",
                    }
                ],
            }
        ],
        ["Secret"],
    )

    ns, override = canonicalize_namespaces(namespaces, ["vault-secret"])
    assert (ns, override) == expected


def test_route(namespaces: list[dict[str, Any]], mocker):
    mocker.patch.object(ob, "aggregate_shared_resources", autospec=True)
    expected = (
        [
            {
                "name": "ns1",
                "cluster": {"name": "cs1"},
                "managedResourceTypes": ["Template"],
                "openshiftResources": [
                    {"provider": "route", "path": "/route/network.yml"}
                ],
            }
        ],
        ["Route"],
    )
    ns, override = canonicalize_namespaces(namespaces, ["route"])
    assert (ns, override) == expected


def test_no_overrides(namespaces: list[dict[str, Any]], mocker):
    mocker.patch.object(ob, "aggregate_shared_resources", autospec=True)
    expected = (
        [
            {
                "name": "ns1",
                "cluster": {"name": "cs1"},
                "managedResourceTypes": ["Template"],
                "openshiftResources": [
                    {"provider": "resource", "path": "/some/path.yml"}
                ],
            }
        ],
        None,
    )

    ns, override = canonicalize_namespaces(namespaces, ["resource"])
    assert (ns, override) == expected


def test_fetch_current_state_ri_not_initialized(
    oc_cs1: oc.OCClient, tmpl1: dict[str, Any]
):
    ri = ResourceInventory()
    oc_cs1.get_items = lambda kind, **kwargs: [tmpl1]  # type: ignore[assignment]
    ri.initialize_resource_type("cs1", "wrong_namespace", "Template")
    ri.initialize_resource_type("wrong_cluster", "ns1", "Template")
    ri.initialize_resource_type("cs1", "ns1", "wrong_kind")
    with pytest.raises(KeyError):
        orb.fetch_current_state(
            oc=oc_cs1,
            ri=ri,
            cluster="cs1",
            namespace="ns1",
            kind="Template",
            resource_names=[],
        )

    for _, _, _, resource in ri:
        assert len(resource["current"]) == 0


def test_fetch_current_state_ri_initialized(oc_cs1: oc.OCClient, tmpl1: dict[str, Any]):
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Template")
    oc_cs1.get_items = lambda kind, **kwargs: [tmpl1]  # type: ignore[assignment]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="Template",
        resource_names=[],
    )

    _, _, _, resource = list(ri)[0]
    assert len(resource["current"]) == 1
    assert "tmpl1" in resource["current"]
    assert resource["current"]["tmpl1"].kind == "Template"


def test_fetch_current_state_kind_not_supported(
    oc_cs1: oc.OCClient, tmpl1: dict[str, Any]
):
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "AnUnsupportedKind")
    oc_cs1.get_items = lambda kind, **kwargs: [tmpl1]  # type: ignore[assignment]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="AnUnsupportedKind",
        resource_names=[],
    )

    _, _, _, resource = list(ri)[0]
    assert len(resource["current"]) == 0


def test_fetch_current_state_long_kind(oc_cs1: oc.OCClient, tmpl1: dict[str, Any]):
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Template.template.openshift.io")
    oc_cs1.get_items = lambda kind, **kwargs: [tmpl1]  # type: ignore[assignment]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="Template.template.openshift.io",
        resource_names=[],
    )

    _, _, _, resource = list(ri)[0]
    assert len(resource["current"]) == 1
    assert "tmpl1" in resource["current"]
    assert resource["current"]["tmpl1"].kind == "Template"


def test_fetch_current_state_long_kind_not_supported(
    oc_cs1: oc.OCClient, tmpl1: dict[str, Any]
):
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "UnknownKind.mysterious.io")
    oc_cs1.get_items = lambda kind, **kwargs: [tmpl1]  # type: ignore[assignment]
    orb.fetch_current_state(
        oc=oc_cs1,
        ri=ri,
        cluster="cs1",
        namespace="ns1",
        kind="UnknownKind.mysterious.io",
        resource_names=[],
    )

    _, _, _, resource = list(ri)[0]
    assert len(resource["current"]) == 0


def test_fetch_states(current_state_spec: CurrentStateSpec, tmpl1: dict[str, Any]):
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Template")
    current_state_spec.oc.get_items = lambda kind, **kwargs: [tmpl1]  # type: ignore[assignment]
    orb.fetch_states(ri=ri, spec=current_state_spec)
    _, _, _, resource = list(ri)[0]
    assert len(resource["current"]) == 1
    assert "tmpl1" in resource["current"]
    assert resource["current"]["tmpl1"].kind == "Template"


def test_fetch_states_unknown_kind(current_state_spec: CurrentStateSpec):
    current_state_spec.kind = "UnknownKind"
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "UnknownKind")
    orb.fetch_states(ri=ri, spec=current_state_spec)
    _, _, _, resource = list(ri)[0]
    assert len(resource["current"]) == 0


def test_fetch_states_oc_error(current_state_spec: CurrentStateSpec):
    current_state_spec.oc.get_items = Mock(  # type: ignore[assignment]
        side_effect=oc.StatusCodeError("something wrong with openshift")
    )
    ri = ResourceInventory()
    ri.initialize_resource_type("cs1", "ns1", "Template")
    orb.fetch_states(ri=ri, spec=current_state_spec)
    assert ri.has_error_registered("cs1")
    _, _, _, resource = list(ri)[0]
    assert len(resource["current"]) == 0
