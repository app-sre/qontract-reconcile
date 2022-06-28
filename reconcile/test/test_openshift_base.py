import logging
from typing import Any, cast
import pytest
import yaml

import reconcile.openshift_base as sut
import reconcile.utils.openshift_resource as resource
from reconcile.test.fixtures import Fixtures
from reconcile.utils import oc
from reconcile.utils.semver_helper import make_semver

fxt = Fixtures("namespaces")


TEST_INT = "test_openshift_resources"
TEST_INT_VER = make_semver(1, 9, 2)


def build_resource(kind: str, api_version: str, name: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "apiVersion": api_version,
        "metadata": {
            "name": name,
        },
    }


@pytest.fixture
def resource_inventory() -> resource.ResourceInventory:
    return resource.ResourceInventory()


@pytest.fixture
def namespaces() -> list[dict[str, Any]]:
    return [fxt.get_anymarkup("valid-ns.yml")]


@pytest.fixture
def oc_cs1() -> oc.OCNative:
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


#
# init_specs_to_fetch tests
#


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


def test_namespaces_managed_types(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCNative,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Template
        managedResourceNames:
        - resource: Template
          resourceNames:
          - tp1
          - tp2
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
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
            parent=namespace,
        ),
    ]

    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=[namespace],
    )
    assert rs == expected


def test_namespaces_managed_types_with_resoruce_type_overrides(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCNative,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Template
        managedResourceNames:
        - resource: Template
          resourceNames:
          - tp1
          - tp2
        managedResourceTypeOverrides:
        - resource: Template
          "override": "Template.something.something"
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
    expected: list[sut.StateSpec] = [
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="Template.something.something",
            resource_names=["tp1", "tp2"],
        ),
        sut.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource={"provider": "resource", "path": "/some/path.yml"},
            parent=namespace,
        ),
    ]
    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=[namespace],
    )

    assert rs == expected


def test_namespaces_managed_types_no_managed_resource_names(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCNative,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Template
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
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
            parent=namespace,
        ),
    ]
    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=[namespace],
    )
    assert rs == expected


def test_namespaces_no_managed_resource_types(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=[namespace],
    )

    assert not rs


def test_namespaces_resources_names_for_unmanaged_type(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Template
        managedResourceNames:
        - resource: Template
          resourceNames:
          - tp1
          - tp2
        - resource: Secret
          resourceNames:
          - s1
          - s2
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )

    with pytest.raises(KeyError):
        sut.init_specs_to_fetch(
            resource_inventory,
            oc_map,
            namespaces=[namespace],
        )


def test_namespaces_type_override_for_unmanaged_type(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Template
        managedResourceTypeOverrides:
        - resource: UnmanagedType
          override: UnmanagedType.unmanagedapi
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
    with pytest.raises(KeyError):
        sut.init_specs_to_fetch(resource_inventory, oc_map, namespaces=[namespace])


def test_namespaces_override_managed_type(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCNative,
) -> None:
    """
    test that the override_managed_types parameter for init_specs_to_fetch takes
    precedence over what might be defined on the namespace. this is relevant for
    integrations that specifically handle only a subset of types e.g. terraform-resources
    only managing Secrets
    """
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Template
        managedResourceNames:
        - resource: Template
          resourceNames:
          - tp1
          - tp2
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
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
            parent=namespace,
        ),
    ]

    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map=oc_map,
        namespaces=[namespace],
        override_managed_types=["LimitRanges"],
    )
    assert rs == expected

    registrations = list(resource_inventory)
    # make sure only the override_managed_type LimitRange is present
    # and not the Template from the namespace
    assert len(registrations) == 1
    cluster, ns, kind, _ = registrations[0]
    assert (cluster, ns, kind) == ("cs1", "ns1", "LimitRanges")


def test_namespaces_managed_fully_qualified_types(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCNative,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Kind.fully.qualified
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
    expected: list[sut.StateSpec] = [
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="Kind.fully.qualified",
            resource_names=None,
        ),
        sut.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource={"provider": "resource", "path": "/some/path.yml"},
            parent=namespace,
        ),
    ]

    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=[namespace],
    )
    assert rs == expected


def test_namespaces_managed_fully_qualified_types_with_resource_names(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCNative,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Kind.fully.qualified
        managedResourceNames:
        - resource: Kind.fully.qualified
          resourceNames:
          - n1
          - n2
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
    expected: list[sut.StateSpec] = [
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="Kind.fully.qualified",
            resource_names=["n1", "n2"],
        ),
        sut.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource={"provider": "resource", "path": "/some/path.yml"},
            parent=namespace,
        ),
    ]

    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=[namespace],
    )
    assert rs == expected


def test_namespaces_managed_mixed_qualified_types_with_resource_names(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCNative,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - Kind.fully.qualified
        - Kind
        managedResourceNames:
        - resource: Kind.fully.qualified
          resourceNames:
          - fname
        - resource: Kind
          resourceNames:
          - name
        openshiftResources:
        - provider: resource
          path: /some/path.yml
        """
    )
    expected: list[sut.StateSpec] = [
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="Kind.fully.qualified",
            resource_names=["fname"],
        ),
        sut.CurrentStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            kind="Kind",
            resource_names=["name"],
        ),
        sut.DesiredStateSpec(
            oc=oc_cs1,
            cluster="cs1",
            namespace="ns1",
            resource={"provider": "resource", "path": "/some/path.yml"},
            parent=namespace,
        ),
    ]

    rs = sut.init_specs_to_fetch(
        resource_inventory,
        oc_map,
        namespaces=[namespace],
    )

    assert len(expected) == len(rs)
    for e in expected:
        assert e in rs


#
# populate state tests
#


def test_populate_current_state(
    resource_inventory: resource.ResourceInventory, oc_cs1: oc.OCNative
):
    """
    test that populate_current_state properly populates the resource inventory
    """
    # prepare client and resource inventory
    oc_cs1.init_api_resources = True
    oc_cs1.api_kind_version = {"Kind": ["fully.qualified/v1", "another.group/v1"]}
    oc_cs1.get_items = lambda kind, **kwargs: [
        build_resource("Kind", "fully.qualified/v1", "name")
    ]
    resource_inventory.initialize_resource_type("cs1", "ns1", "Kind.fully.qualified")

    # process
    spec = sut.CurrentStateSpec(
        oc=oc_cs1,
        cluster="cs1",
        namespace="ns1",
        kind="Kind.fully.qualified",
        resource_names=["name"],
    )
    sut.populate_current_state(spec, resource_inventory, TEST_INT, TEST_INT_VER)

    # verify
    cluster, namespace, kind, data = next(iter(resource_inventory))
    assert (cluster, namespace, kind) == ("cs1", "ns1", "Kind.fully.qualified")
    assert data["current"]["name"] == resource.OpenshiftResource(
        build_resource("Kind", "fully.qualified/v1", "name"), TEST_INT, TEST_INT_VER
    )


def test_populate_current_state_unknown_kind(
    resource_inventory: resource.ResourceInventory, oc_cs1: oc.OCNative, mocker
):
    """
    test that a missing kind in the cluster is catched early on
    """
    oc_cs1.init_api_resources = True
    oc_cs1.api_kind_version = {"Kind": ["some.other.group/v1"]}
    get_item_mock = mocker.patch.object(oc.OCNative, "get_items", autospec=True)

    spec = sut.CurrentStateSpec(
        oc=oc_cs1,
        cluster="cs1",
        namespace="ns1",
        kind="Kind.fully.qualified",
        resource_names=["name"],
    )
    sut.populate_current_state(spec, resource_inventory, TEST_INT, TEST_INT_VER)

    assert len(list(iter(resource_inventory))) == 0
    get_item_mock.assert_not_called()


def test_populate_current_state_resource_name_filtering(
    resource_inventory: resource.ResourceInventory, oc_cs1: oc.OCNative, mocker
):
    """
    test if the resource names are passed properly to the oc client when fetching items
    """
    get_item_mock = mocker.patch.object(oc.OCNative, "get_items", autospec=True)

    spec = sut.CurrentStateSpec(
        oc=oc_cs1,
        cluster="cs1",
        namespace="ns1",
        kind="Kind.fully.qualified",
        resource_names=["name1", "name2"],
    )
    sut.populate_current_state(spec, resource_inventory, TEST_INT, TEST_INT_VER)

    get_item_mock.assert_called_with(
        oc_cs1,
        "Kind.fully.qualified",
        namespace="ns1",
        resource_names=["name1", "name2"],
    )


#
# determine_user_key_for_access tests
#


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
