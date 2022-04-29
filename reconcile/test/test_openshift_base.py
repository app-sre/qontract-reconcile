import logging
from typing import Any, cast
import pytest
import yaml

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


def test_namespaces_managed_types(
    resource_inventory: resource.ResourceInventory,
    oc_map: oc.OC_Map,
    oc_cs1: oc.OCClient,
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
    oc_cs1: oc.OCClient,
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
          "override": "something.something.Template"
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
            kind="something.something.Template",
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
    oc_cs1: oc.OCClient,
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
    namespaces: list[dict[str, Any]],
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
          override: unmanagedapi.UnmanagedType
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
    oc_cs1: oc.OCClient,
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
    oc_cs1: oc.OCClient,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - fullyqualified.Kind
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
            kind="fullyqualified.Kind",
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
    oc_cs1: oc.OCClient,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - fullyqualified.Kind
        managedResourceNames:
        - resource: fullyqualified.Kind
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
            kind="fullyqualified.Kind",
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
    oc_cs1: oc.OCClient,
) -> None:
    namespace = yaml.safe_load(
        """
        name: ns1
        cluster:
          name: cs1
        managedResourceTypes:
        - fullyqualified.Kind
        - Kind
        managedResourceNames:
        - resource: fullyqualified.Kind
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
            kind="fullyqualified.Kind",
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
