import pytest

from reconcile.utils.openshift_resource import ConstructResourceError
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import (
    ResourceInventory,
    ResourceNotManagedError,
    build_secret,
)
from reconcile.utils.semver_helper import make_semver

from .fixtures import Fixtures

fxt = Fixtures("openshift_resource")

TEST_INT = "test_openshift_resources"
TEST_INT_VER = make_semver(1, 9, 2)


def build_resource(kind: str, api_version: str, name: str):
    body = {
        "kind": kind,
        "apiVersion": api_version,
        "metadata": {
            "name": name,
        },
    }
    return OR(body, "int", "int-v")


#
# OpenshiftResource tests
#


def test_obj_intersect_equal_status_depth_0_current():
    desired = {
        "kind": "kind",
        "metadata": {
            "name": "name",
        },
    }
    current = {
        "kind": "kind",
        "metadata": {
            "name": "name",
        },
        "status": "status",
    }
    d_item = OR(desired, TEST_INT, TEST_INT_VER)
    c_item = OR(current, TEST_INT, TEST_INT_VER)

    assert d_item == c_item


def test_obj_intersect_equal_status_depth_0_desired():
    desired = {
        "kind": "kind",
        "metadata": {
            "name": "name",
        },
        "status": "nonsense",
    }
    current = {
        "kind": "kind",
        "metadata": {
            "name": "name",
        },
        "status": "status",
    }
    d_item = OR(desired, TEST_INT, TEST_INT_VER)
    c_item = OR(current, TEST_INT, TEST_INT_VER)

    assert d_item == c_item


def test_obj_intersect_equal_status_depth_not_0():
    desired = {
        "kind": "kind",
        "metadata": {
            "name": "name",
        },
        "spec": {
            "status": "status",
        },
    }
    current = {
        "kind": "kind",
        "metadata": {
            "name": "name",
        },
    }
    d_item = OR(desired, TEST_INT, TEST_INT_VER)
    c_item = OR(current, TEST_INT, TEST_INT_VER)

    assert d_item != c_item


def test_verify_valid_k8s_object():
    resource = fxt.get_anymarkup("valid_resource.yml")
    openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

    assert openshift_resource.verify_valid_k8s_object() is None


def test_verify_valid_k8s_object_false():
    resource = fxt.get_anymarkup("invalid_resource.yml")

    with pytest.raises(ConstructResourceError):
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
        assert openshift_resource.verify_valid_k8s_object() is None


def test_invalid_name_format():
    resource = fxt.get_anymarkup("invalid_resource_name_format.yml")

    with pytest.raises(ConstructResourceError):
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
        assert openshift_resource.verify_valid_k8s_object() is None


def test_invalid_name_too_long():
    resource = fxt.get_anymarkup("invalid_resource_name_too_long.yml")

    with pytest.raises(ConstructResourceError):
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
        assert openshift_resource.verify_valid_k8s_object() is None


def test_invalid_container_name_format():
    resource = fxt.get_anymarkup("invalid_resource_container_name_format.yml")

    with pytest.raises(ConstructResourceError):
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
        assert openshift_resource.verify_valid_k8s_object() is None


def test_invalid_container_name_too_long():
    resource = fxt.get_anymarkup("invalid_resource_container_name_too_long.yml")

    with pytest.raises(ConstructResourceError):
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
        assert openshift_resource.verify_valid_k8s_object() is None


def test_annotates_resource():
    resource = fxt.get_anymarkup("annotates_resource.yml")
    openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

    assert openshift_resource.has_qontract_annotations() is False

    annotated = openshift_resource.annotate()
    assert annotated.has_qontract_annotations() is True


def test_sha256sum_properly_ignores_some_params():
    resources = fxt.get_anymarkup("ignores_params.yml")

    assert (
        OR(resources[0], TEST_INT, TEST_INT_VER).annotate().sha256sum()
        == OR(resources[1], TEST_INT, TEST_INT_VER).annotate().sha256sum()
    )


def test_sha256sum():
    resource = fxt.get_anymarkup("sha256sum.yml")

    openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

    assert (
        openshift_resource.sha256sum()
        == "1366d8ef31f0d83419d25b446e61008b16348b9efee2216873856c49cede6965"
    )

    annotated = openshift_resource.annotate()

    assert (
        annotated.sha256sum()
        == "1366d8ef31f0d83419d25b446e61008b16348b9efee2216873856c49cede6965"
    )

    assert annotated.has_valid_sha256sum()

    annotated.body["metadata"]["annotations"]["qontract.sha256sum"] = "test"

    assert (
        annotated.sha256sum()
        == "1366d8ef31f0d83419d25b446e61008b16348b9efee2216873856c49cede6965"
    )

    assert not annotated.has_valid_sha256sum()


def test_has_owner_reference_true():
    resource = {
        "kind": "kind",
        "metadata": {"name": "resource", "ownerReferences": [{"name": "owner"}]},
    }
    openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
    assert openshift_resource.has_owner_reference()


def test_has_owner_reference_false():
    resource = {"kind": "kind", "metadata": {"name": "resource"}}
    openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
    assert not openshift_resource.has_owner_reference()


def test_secret_string_data():
    resource = {
        "kind": "Secret",
        "metadata": {"name": "resource"},
        "stringData": {"k": "v"},
    }
    expected = {
        "kind": "Secret",
        "metadata": {"annotations": {}, "name": "resource"},
        "data": {"k": "dg=="},
    }
    result = OR.canonicalize(resource)
    assert result == expected


def test_managed_cluster_label_ignore():
    desired = {
        "apiVersion": "cluster.open-cluster-management.io/v1",
        "kind": "ManagedCluster",
        "metadata": {
            "labels": {
                "cloud": "Amazon",
                "vendor": "OpenShift",
                "cluster.open-cluster-management.io/clusterset": "default",
                "name": "xxx",
            },
            "name": "xxx",
        },
        "spec": {"hubAcceptsClient": True},
    }
    current = {
        "apiVersion": "cluster.open-cluster-management.io/v1",
        "kind": "ManagedCluster",
        "metadata": {
            "labels": {
                "cloud": "Amazon",
                "cluster.open-cluster-management.io/clusterset": "default",
                "name": "xxx",
                "vendor": "OpenShift",
                "clusterID": "yyy",
                "feature.open-cluster-management.io/addon-work-manager": "available",
                "managed-by": "platform",
                "openshiftVersion": "x.y.z",
            },
            "name": "xxx",
        },
        "spec": {"hubAcceptsClient": True},
    }

    d_r = OR(desired, TEST_INT, TEST_INT_VER)
    c_r = OR(current, TEST_INT, TEST_INT_VER)
    assert d_r == c_r
    assert d_r.sha256sum() == c_r.sha256sum()


def test_build_secret():
    value = "value"
    encoded_value = "dmFsdWU="
    res = build_secret(
        name="name",
        integration=TEST_INT,
        integration_version=TEST_INT_VER,
        unencoded_data={
            "field": value,
            "empty": "",
        },
    )

    # test metadata
    assert res.kind == "Secret"
    assert res.name == "name"
    assert res.integration == TEST_INT
    assert res.integration_version == TEST_INT_VER

    # assert data section
    assert len(res.body["data"]) == 2
    assert res.body["data"]["field"] == encoded_value
    assert not res.body["data"]["empty"]


def test_openshift_resource_kind_and_group():
    res = build_resource("Deployment", "apps/v1", "foo")
    assert res.kind_and_group == "Deployment.apps"


def test_openshift_resource_kind_no_group():
    res = build_resource("Pod", "v1", "foo")
    assert res.kind_and_group == "Pod"


#
# ResourceInventory tests
#


def test_resource_inventory_add_desired():
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster="cl", namespace="ns", resource_type="Deployment"
    )
    res = build_resource("Deployment", "apps/v1", "name")
    ri.add_desired_resource("cl", "ns", res)

    for cluster_name, namespace_name, resource_type, resource in ri:
        assert cluster_name == "cl"
        assert namespace_name == "ns"
        assert resource_type == "Deployment"
        assert resource["desired"]["name"] == res
        assert not resource["use_admin_token"]["name"]


def test_resource_inventory_add_desired_without_registration():
    """
    test that adding a desired state fails if the type has not been
    registered upfront
    """
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster="cl", namespace="ns", resource_type="ApprovedType"
    )

    with pytest.raises(KeyError):
        res = build_resource("AnotherType", "apps/v1", "foo")
        ri.add_desired_resource("cl", "ns", res)


def test_resource_inventory_add_desired_with_managed_name():
    """
    test that adding a desired state succeeds if it's name is registered
    as being managed
    """
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster="cl", namespace="ns", resource_type="Deployment", managed_names=["name"]
    )

    res = build_resource("Deployment", "apps/v1", "name")
    ri.add_desired_resource("cl", "ns", res)


def test_resource_inventory_add_desired_without_managed_name():
    """
    test that adding a desired state fails if it's name is not registered
    as being managed
    """
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster="cl", namespace="ns", resource_type="Deployment", managed_names=["name"]
    )

    with pytest.raises(ResourceNotManagedError):
        res = build_resource("Deployment", "apps/v1", "an-unmanaged-name")
        ri.add_desired_resource("cl", "ns", res)


def test_resource_inventory_add_desired_privileged():
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster="cl",
        namespace="ns",
        resource_type="Deployment",
    )
    res = build_resource("Deployment", "apps/v1", "name")
    ri.add_desired_resource("cl", "ns", res, privileged=True)

    for cluster_name, namespace_name, resource_type, resource in ri:
        assert cluster_name == "cl"
        assert namespace_name == "ns"
        assert resource_type == "Deployment"
        assert resource["desired"]["name"] == res
        assert resource["use_admin_token"]["name"]


def test_resource_inventory_add_desired_resource_short_kind():
    """
    test that add_desired_resource uses the short kind name if the short
    name has been registered for the namespace
    """
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster="cl", namespace="ns", resource_type="Deployment"
    )
    res = build_resource("Deployment", "apps/v1", "foo")
    ri.add_desired_resource("cl", "ns", res)

    assert len(list(ri)) == 1

    cluster_name, namespace_name, resource_type, resource = list(ri)[0]
    assert cluster_name == "cl"
    assert namespace_name == "ns"
    assert resource_type == "Deployment"
    assert resource["desired"].get("foo")


def test_resource_inventory_add_desired_resource_long_kind():
    """
    test that add_desired_resource uses the long kind name if the long
    name has been registered for the namespace
    """
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster="cl", namespace="ns", resource_type="Deployment.apps"
    )
    res = build_resource("Deployment", "apps/v1", "foo")
    ri.add_desired_resource("cl", "ns", res)

    assert len(list(ri)) == 1

    cluster_name, namespace_name, resource_type, resource = list(ri)[0]
    assert cluster_name == "cl"
    assert namespace_name == "ns"
    assert resource_type == "Deployment.apps"
    assert resource["desired"].get("foo")


def test_resource_inventory_add_desired_resource_mixed_kinds():
    """
    test that add_desired_resource prefers the long kind name if both the long
    and short kind have been registered with the namespace
    """
    ri = ResourceInventory()
    ri.initialize_resource_type(
        cluster="cl", namespace="ns", resource_type="Deployment.apps"
    )
    ri.initialize_resource_type(
        cluster="cl", namespace="ns", resource_type="Deployment"
    )
    res = build_resource("Deployment", "apps/v1", "foo")
    ri.add_desired_resource("cl", "ns", res)

    assert len(list(ri)) == 2

    for _, _, resource_type, resource in ri:
        if resource_type == "Deployments.app":
            assert resource["desired"].get("foo")
        elif resource_type == "Deployment":
            assert len(resource["desired"]) == 0
