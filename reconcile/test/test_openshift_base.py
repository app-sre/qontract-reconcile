import logging
from typing import (
    Any,
    Mapping,
    Optional,
)
from unittest.mock import patch

import pytest
import yaml
from kubernetes.dynamic import Resource
from pydantic import BaseModel
from pytest_mock import MockerFixture

import reconcile.openshift_base as sut
import reconcile.utils.openshift_resource as resource
from reconcile.test.fixtures import Fixtures
from reconcile.utils import oc
from reconcile.utils.differ import (
    DiffPair,
    DiffResult,
)
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
@patch("reconcile.utils.oc.OCNative")
def oc_cs1(self) -> oc.OCClient:
    return oc.OCNative(cluster_name="cs1", server="server", token="token", local=True)


@pytest.fixture
def oc_map(mocker, oc_cs1: oc.OCNative) -> oc.OC_Map:
    def get_cluster(cluster: str, privileged: bool = False):
        if cluster == "cs1":
            return oc_cs1

        return (
            oc.OCLogMsg(
                log_level=logging.DEBUG, message=f"[{cluster}] cluster skipped"
            ),
        )

    oc_map = mocker.patch("reconcile.utils.oc.OC_Map", autospec=True).return_value
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


@pytest.fixture
def api_resources():
    r1 = Resource(
        prefix="",
        kind="Kind",
        group="fully.qualified",
        api_version="v1",
        namespaced=True,
    )
    r2 = Resource(
        prefix="",
        kind="Kind",
        group="another.group",
        api_version="v1",
        namespaced=True,
    )
    return {"Kind": [r1, r2]}


def test_populate_current_state(
    api_resources, resource_inventory: resource.ResourceInventory, oc_cs1: oc.OCNative
):
    """
    test that populate_current_state properly populates the resource inventory
    """
    # prepare client and resource inventory
    oc_cs1.init_api_resources = True
    oc_cs1.api_resources = api_resources
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
    k1 = Resource(prefix="", group="some.other.group", api_version="v1", kind="Kind")
    oc_cs1.api_resources = {"Kind": [k1]}
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
    spec = sut.CurrentStateSpec(
        oc=oc_cs1,
        cluster="cs1",
        namespace="ns1",
        kind="Kind.fully.qualified",
        resource_names=["name1", "name2"],
    )
    sut.populate_current_state(spec, resource_inventory, TEST_INT, TEST_INT_VER)

    oc_cs1.get_items.assert_called_with(
        "Kind.fully.qualified",
        namespace="ns1",
        resource_names=["name1", "name2"],
    )


#
# determine_user_keys_for_access tests
#


class OpenshiftBaseAuthService(BaseModel):
    service: str


class OpenshiftBaseCluster(BaseModel):
    name: str
    auth: list[OpenshiftBaseAuthService]


class OpenshiftBaseUser(BaseModel):
    org_username: str
    github_username: str


@pytest.mark.parametrize(
    "auth, expected",
    [
        # dicts
        ([{"service": "github-org"}], ["github_username"]),
        ([{"service": "github-org-team"}], ["github_username"]),
        ([{"service": "oidc"}], ["org_username"]),
        (
            [{"service": "oidc"}, {"service": "github-org-team"}],
            ["org_username", "github_username"],
        ),
        (
            [{"service": "github-org"}, {"service": "github-org-team"}],
            ["github_username"],
        ),
        # class
        ([OpenshiftBaseAuthService(service="github-org")], ["github_username"]),
        ([OpenshiftBaseAuthService(service="github-org-team")], ["github_username"]),
        ([OpenshiftBaseAuthService(service="oidc")], ["org_username"]),
        (
            [
                OpenshiftBaseAuthService(service="oidc"),
                OpenshiftBaseAuthService(service="github-org-team"),
            ],
            ["org_username", "github_username"],
        ),
        (
            [
                OpenshiftBaseAuthService(service="github-org"),
                OpenshiftBaseAuthService(service="github-org-team"),
            ],
            ["github_username"],
        ),
        # backward_compatibility
        ([], ["github_username"]),
    ],
)
def test_determine_user_keys_for_access(auth, expected):
    assert sut.determine_user_keys_for_access("cluster-name", auth) == expected


def test_determine_user_keys_enforced_user_keys():
    assert sut.determine_user_keys_for_access(
        "cluster-name",
        [{"service": "github-org"}],
        enforced_user_keys=["my-enforced-key"],
    ) == ["my-enforced-key"]


def test_determine_user_keys_for_access_not_implemented():
    auth = {"service": "not-implemented"}
    with pytest.raises(NotImplementedError):
        sut.determine_user_keys_for_access("cluster-name", [auth])


def test_is_namespace_deleted_true():
    ns = {"delete": True}
    assert sut.is_namespace_deleted(ns) is True


def test_is_namespace_deleted_false():
    ns = {"delete": False}
    assert sut.is_namespace_deleted(ns) is False


def test_is_namespace_deleted_none():
    ns = {"delete": None}
    assert sut.is_namespace_deleted(ns) is False


def test_is_namespace_deleted_empty():
    assert sut.is_namespace_deleted({}) is False


def test_user_has_cluster_access(mocker: MockerFixture):
    mocker.patch.object(
        sut, "determine_user_keys_for_access", return_value=["org_username"]
    )
    user = OpenshiftBaseUser(org_username="user_org", github_username="user_github")
    cluster = OpenshiftBaseCluster(
        name="cluster", auth=[OpenshiftBaseAuthService(service="oidc")]
    )
    assert sut.user_has_cluster_access(user, cluster, ["user_org"])
    assert not sut.user_has_cluster_access(user, cluster, ["another_user"])


@pytest.fixture
def apply_options() -> sut.ApplyOptions:
    options = sut.ApplyOptions(
        dry_run=True,
        no_dry_run_skip_compare=False,
        wait_for_namespace=True,
        recycle_pods=True,
        take_over=False,
        override_enable_deletion=False,
        caller=None,
        all_callers=None,
        privileged=False,
        enable_deletion=False,
    )
    return options


def build_openshift_resource(
    kind: str,
    api_version: str,
    name: str,
    extra_body: Optional[dict[str, Any]],
    integration: str = "",
    integration_version: str = "",
    error_details: str = "",
    caller_name: str = "",
) -> resource.OpenshiftResource:
    body = {
        "kind": kind,
        "apiVersion": api_version,
        "metadata": {
            "name": name,
        },
    }
    if extra_body:
        body = body | extra_body

    return resource.OpenshiftResource(
        body=body,
        integration=integration,
        integration_version=integration_version,
        error_details=error_details,
        caller_name=caller_name,
        validate_k8s_object=False,
    )


def build_openshift_resource_1() -> resource.OpenshiftResource:
    spec = {"spec": {"test-attr": "test-value-1"}}
    return build_openshift_resource(
        kind="test-kind", api_version="v1", name="test-resource", extra_body=spec
    )


def build_openshift_resource_2() -> resource.OpenshiftResource:
    spec = {"spec": {"test-attr": "test-value-1"}}
    return build_openshift_resource(
        kind="test-kind", api_version="v1", name="test-resource", extra_body=spec
    )


@pytest.fixture
def diff_result() -> DiffResult:
    r1 = build_openshift_resource_1()
    r2 = build_openshift_resource_2()
    return DiffResult(
        add={"test-resource": r1},
        change={"test-resource": DiffPair(r1, r2)},
        delete={"test-resource": r1},
        identical={},
    )


def test_handle_new_resources(
    mocker: MockerFixture,
    oc_map: oc.OC_Map,
    resource_inventory: resource.ResourceInventory,
    diff_result: DiffResult,
    apply_options: sut.ApplyOptions,
):
    apply_mock = mocker.patch.object(sut, "apply", autospec=True)
    cluster = "test-cluster"
    namespace = "test-namespace"
    resource_type = "test-Kind"
    data = {"use_admin_token": {"test-resource": False}}

    actions = sut.handle_new_resources(
        oc_map=oc_map,
        ri=resource_inventory,
        new_resources=diff_result.add,
        cluster=cluster,
        namespace=namespace,
        resource_type=resource_type,
        data=data,
        options=apply_options,
    )

    assert len(actions) == 1
    apply_expected_args = {
        "dry_run": True,
        "oc_map": oc_map,
        "cluster": "test-cluster",
        "namespace": "test-namespace",
        "resource_type": "test-Kind",
        "resource": diff_result.add["test-resource"],
        "wait_for_namespace": True,
        "recycle_pods": True,
        "privileged": False,
    }
    apply_mock.assert_called_with(**apply_expected_args)


def test_handle_modified_resources(
    mocker: MockerFixture,
    oc_map: oc.OC_Map,
    resource_inventory: resource.ResourceInventory,
    diff_result: DiffResult,
    apply_options: sut.ApplyOptions,
):
    apply_mock = mocker.patch.object(sut, "apply", autospec=True)
    cluster = "test-cluster"
    namespace = "test-namespace"
    resource_type = "test-Kind"
    data = {"use_admin_token": {"test-resource": False}}

    modified_resources = diff_result.change

    actions = sut.handle_modified_resources(
        oc_map=oc_map,
        ri=resource_inventory,
        modified_resources=modified_resources,
        cluster=cluster,
        namespace=namespace,
        resource_type=resource_type,
        data=data,
        options=apply_options,
    )

    assert len(actions) == 1
    apply_expected_args = {
        "dry_run": True,
        "oc_map": oc_map,
        "cluster": "test-cluster",
        "namespace": "test-namespace",
        "resource_type": "test-Kind",
        "resource": diff_result.change["test-resource"].desired,
        "wait_for_namespace": True,
        "recycle_pods": True,
        "privileged": False,
    }
    apply_mock.assert_called_with(**apply_expected_args)


def test_handle_deleted_resources(
    mocker: MockerFixture,
    oc_map: oc.OC_Map,
    resource_inventory: resource.ResourceInventory,
    diff_result: DiffResult,
    apply_options: sut.ApplyOptions,
):
    delete_mock = mocker.patch.object(sut, "delete", autospec=True)

    # mock has_qontract_annotations to own the resource
    hqa = mocker.patch.object(
        resource.OpenshiftResource, "has_qontract_annotations", autospec=True
    )
    hqa.return_value = True

    cluster = "test-cluster"
    namespace = "test-namespace"
    resource_type = "test-Kind"
    data = {"use_admin_token": {"test-resource": False}}

    actions = sut.handle_deleted_resources(
        oc_map=oc_map,
        ri=resource_inventory,
        deleted_resources=diff_result.delete,
        cluster=cluster,
        namespace=namespace,
        resource_type=resource_type,
        data=data,
        options=apply_options,
    )

    assert len(actions) == 1
    delete_expected_args = {
        "dry_run": True,
        "oc_map": oc_map,
        "cluster": "test-cluster",
        "namespace": "test-namespace",
        "resource_type": "test-Kind",
        "name": "test-resource",
        "enable_deletion": False,
        "privileged": False,
    }
    delete_mock.assert_called_with(**delete_expected_args)


# Fixtures does not work with parametrize
# functions are used to build resources instead
@pytest.mark.parametrize(
    "data, len_actions, apply_calls, delete_calls",
    [
        (
            {
                "current": {},
                "desired": {"test-resource": build_openshift_resource_1()},
                "use_admin_token": {},
            },
            1,
            1,
            0,
        ),
        (
            {
                "current": {"test-resource": build_openshift_resource_1()},
                "desired": {"test-resource": build_openshift_resource_2()},
                "use_admin_token": {},
            },
            1,
            1,
            0,
        ),
        (
            {
                "current": {"test-resource": build_openshift_resource_1()},
                "desired": {},
                "use_admin_token": {},
            },
            1,
            0,
            1,
        ),
    ],
)
def test_realize_resource_data_3way_diff(
    mocker: MockerFixture,
    oc_map: oc.OC_Map,
    resource_inventory: resource.ResourceInventory,
    apply_options: sut.ApplyOptions,
    data: Mapping[str, Any],
    len_actions: int,
    apply_calls: int,
    delete_calls: int,
):
    apply_mock = mocker.patch.object(sut, "apply", autospec=True)
    delete_mock = mocker.patch.object(sut, "delete", autospec=True)
    # Patch has_qontract_annotations to own the resource
    mocker.patch.object(
        resource.OpenshiftResource, "has_qontract_annotations", autospec=True
    ).return_value = True

    ri_item = ("test-cluster", "test-namespace", "test-kind", data)
    actions = sut._realize_resource_data_3way_diff(
        ri_item=ri_item, oc_map=oc_map, ri=resource_inventory, options=apply_options
    )
    assert len(actions) == len_actions
    assert apply_mock.call_count == apply_calls
    assert delete_mock.call_count == delete_calls


def test_get_state_count_combinations():
    state = [
        {"cluster": "c1"},
        {"cluster": "c2"},
        {"cluster": "c1"},
        {"cluster": "c3"},
        {"cluster": "c2"},
    ]
    expected = {"c1": 2, "c2": 2, "c3": 1}
    assert expected == sut.get_state_count_combinations(state)
