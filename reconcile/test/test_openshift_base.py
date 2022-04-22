import logging
from typing import Any, List, cast
import pytest

import reconcile.openshift_base as sut
import reconcile.utils.openshift_resource as resource
from reconcile.test.fixtures import Fixtures
from reconcile.utils import oc

fxt = Fixtures("namespaces")


@pytest.fixture
def resource_inventory() -> resource.ResourceInventory:
    return resource.ResourceInventory()


@pytest.fixture
def namespaces() -> list[dict[str, Any]]:
    return [fxt.get_anymarkup("valid-ns.yml")]


@pytest.fixture
def oc_cs1() -> oc.OCClient:
    return cast(oc.OCNative, oc.OC(cluster_name="cs1", server="", token="", local=True))


@pytest.fixture
def oc_map(mocker, oc_cs1: oc.OCNative) -> oc.OC_Map:
    def get_cluster(cluster: str, privileged: bool = False):
        if cluster == "cs1":
            return oc_cs1
        else:
            return (
                oc.OCLogMsg(
                    log_level=logging.DEBUG, message=f"[{cluster}] cluster skipped"
                ),
            )

    oc_map = mocker.patch("reconcile.utils.oc.OC_Map", autospec=True).return_value
    oc_map.get.mock_add_spec(oc.OC_Map.get)
    oc_map.get.side_effect = get_cluster
    return oc_map


def test_only_cluster_or_namespace(
    resource_inventory: resource.ResourceInventory, oc_map: oc.OC_Map
) -> None:
    with pytest.raises(KeyError):
        sut.init_specs_to_fetch(
            ri=resource_inventory,
            oc_map=oc_map,
            namespaces=[{"foo": "bar"}],
            clusters=[{"name": "cs1"}],
        )


def test_no_cluster_or_namespace(
    resource_inventory: resource.ResourceInventory, oc_map: oc.OC_Map
) -> None:
    with pytest.raises(KeyError):
        sut.init_specs_to_fetch(
            ri=resource_inventory, oc_map=oc_map, namespaces=None, clusters=None
        )


def assert_specs_match(
    result: List[sut.StateSpec], expected: List[sut.StateSpec]
) -> None:
    """Assert that two list of StateSpec are equal. Needed since StateSpec
    doesn't implement __eq__ and it's not worth to add for we will convert
    it to a dataclass when we move to Python 3.9"""
    assert [r.__dict__ for r in result] == [e.__dict__ for e in expected]


def test_namespaces_managed(
    resource_inventory: resource.ResourceInventory,
    namespaces: list[dict[str, Any]],
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCClient,
) -> None:
    expected: list[sut.StateSpec] = [
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="Template",
            resource_names=["tp1", "tp2"],
        ),
        sut.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource={"provider": "resource", "path": "/some/path.yml"},
            parent=namespaces[0],
        ),
    ]

    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=namespaces,
    )
    assert_specs_match(rs, expected)


def test_namespaces_managed_with_overrides(
    resource_inventory: resource.ResourceInventory,
    namespaces: list[dict[str, Any]],
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCClient,
) -> None:
    namespaces[0]["managedResourceTypeOverrides"] = [
        {"resource": "Template", "override": "something.template"}
    ]
    expected: list[sut.StateSpec] = [
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="something.template",
            resource_names=["tp1", "tp2"],
        ),
        sut.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource={"provider": "resource", "path": "/some/path.yml"},
            parent=namespaces[0],
        ),
    ]
    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=namespaces,
    )

    assert_specs_match(rs, expected)


def test_namespaces_no_managedresourcenames(
    resource_inventory: resource.ResourceInventory,
    namespaces: list[dict[str, Any]],
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCClient,
) -> None:
    namespaces[0]["managedResourceNames"] = None
    namespaces[0]["managedResourceTypeOverrides"] = None
    expected: list[sut.StateSpec] = [
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="Template",
            resource_names=None,
        ),
        sut.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource={"provider": "resource", "path": "/some/path.yml"},
            parent=namespaces[0],
        ),
    ]
    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=namespaces,
    )
    assert_specs_match(rs, expected)


def test_namespaces_no_managedresourcetypes(
    resource_inventory: resource.ResourceInventory,
    namespaces: list[dict[str, Any]],
    oc_map: oc.OC_Map,
) -> None:
    namespaces[0]["managedResourceTypes"] = None
    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=namespaces,
    )

    assert not rs


def test_namespaces_extra_managed_resource_name(
    resource_inventory: resource.ResourceInventory,
    namespaces: list[dict[str, Any]],
    oc_map: oc.OC_Map,
) -> None:
    namespaces[0]["managedResourceNames"].append(
        {
            "resource": "Secret",
            "resourceNames": ["s1", "s2"],
        },
    )

    with pytest.raises(KeyError):
        sut.init_specs_to_fetch(
            resource_inventory,
            oc_map,
            namespaces=namespaces,
        )


def test_namespaces_extra_override(
    resource_inventory: resource.ResourceInventory,
    namespaces: list[dict[str, Any]],
    oc_map: oc.OC_Map,
) -> None:
    namespaces[0]["managedResourceTypeOverrides"] = [
        {
            "resource": "Project",
            "override": "something.project",
        }
    ]

    with pytest.raises(KeyError):
        sut.init_specs_to_fetch(resource_inventory, oc_map, namespaces=namespaces)


def test_namespaces_override_managed_type(
    resource_inventory: resource.ResourceInventory,
    namespaces: list[dict[str, Any]],
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCClient,
) -> None:
    namespaces[0]["managedResourceTypeOverrides"] = [
        {
            "resource": "Project",
            "override": "wonderful.project",
        }
    ]

    expected: list[sut.StateSpec] = [
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="LimitRanges",
            resource_names=None,
        ),
        sut.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource={"provider": "resource", "path": "/some/path.yml"},
            parent=namespaces[0],
        ),
    ]

    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map=oc_map,
        namespaces=namespaces,
        override_managed_types=["LimitRanges"],
    )
    assert_specs_match(rs, expected)

    registrations = list(resource_inventory)
    # make sure only the override_managed_type LimitRange is present
    # and not the Template from the namespace
    assert len(registrations) == 1
    cluster, namespace, kind, _ = registrations[0]
    assert (cluster, namespace, kind) == ("cs1", "ns1", "LimitRanges")


def test_determine_user_key_for_access_github_org():
    cluster_info = {"auth": {"service": "github-org"}}
    user_key = sut.determine_user_key_for_access(cluster_info)
    assert user_key == "github_username"


def test_determine_user_key_for_access_github_org_team():
    cluster_info = {"auth": {"service": "github-org-team"}}
    user_key = sut.determine_user_key_for_access(cluster_info)
    assert user_key == "github_username"


def test_determine_user_key_for_access_oidc():
    cluster_info = {"auth": {"service": "oidc"}}
    user_key = sut.determine_user_key_for_access(cluster_info)
    assert user_key == "org_username"


def test_determine_user_key_for_access_not_implemented():
    cluster_info = {"auth": {"service": "not-implemented"}, "name": "c"}
    with pytest.raises(NotImplementedError):
        sut.determine_user_key_for_access(cluster_info)
