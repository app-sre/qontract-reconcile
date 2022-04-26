import pytest

from reconcile.utils.semver_helper import make_semver
from reconcile.utils.openshift_resource import (
    OpenshiftResource as OR,
    ConstructResourceError,
    build_secret,
)


from .fixtures import Fixtures

fxt = Fixtures("openshift_resource")

TEST_INT = "test_openshift_resources"
TEST_INT_VER = make_semver(1, 9, 2)


class TestOpenshiftResource:
    @staticmethod
    def test_verify_valid_k8s_object():
        resource = fxt.get_anymarkup("valid_resource.yml")
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

        assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_verify_valid_k8s_object_false():
        resource = fxt.get_anymarkup("invalid_resource.yml")

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_invalid_name_format():
        resource = fxt.get_anymarkup("invalid_resource_name_format.yml")

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_invalid_name_too_long():
        resource = fxt.get_anymarkup("invalid_resource_name_too_long.yml")

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_invalid_container_name_format():
        resource = fxt.get_anymarkup("invalid_resource_container_name_format.yml")

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_invalid_container_name_too_long():
        resource = fxt.get_anymarkup("invalid_resource_container_name_too_long.yml")

        with pytest.raises(ConstructResourceError):
            openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
            assert openshift_resource.verify_valid_k8s_object() is None

    @staticmethod
    def test_annotates_resource():
        resource = fxt.get_anymarkup("annotates_resource.yml")
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)

        assert openshift_resource.has_qontract_annotations() is False

        annotated = openshift_resource.annotate()
        assert annotated.has_qontract_annotations() is True

    @staticmethod
    def test_sha256sum_properly_ignores_some_params():
        resources = fxt.get_anymarkup("ignores_params.yml")

        assert (
            OR(resources[0], TEST_INT, TEST_INT_VER).annotate().sha256sum()
            == OR(resources[1], TEST_INT, TEST_INT_VER).annotate().sha256sum()
        )

    @staticmethod
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

    @staticmethod
    def test_has_owner_reference_true():
        resource = {
            "kind": "kind",
            "metadata": {"name": "resource", "ownerReferences": [{"name": "owner"}]},
        }
        openshift_resource = OR(resource, TEST_INT, TEST_INT_VER)
        assert openshift_resource.has_owner_reference()

    @staticmethod
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
