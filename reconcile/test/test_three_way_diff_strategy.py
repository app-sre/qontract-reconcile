import pytest

from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.three_way_diff_strategy import (
    is_cpu_mutation,
    three_way_diff_using_hash,
)

from .fixtures import Fixtures

fxt = Fixtures("openshift_resource")


@pytest.fixture
def deployment():
    resource = fxt.get_anymarkup("deployment.yml")
    yield resource


def test_3wpd_change_current_not_in_desired_should_not_apply(deployment):
    d_item = OR(deployment, "", "")
    c_item = d_item.annotate(canonicalize=False)

    c_item.body["spec"]["manual_added_attr"] = 5
    assert three_way_diff_using_hash(c_item, d_item) is True


def test_3wpd_equal_objects_should_not_apply(deployment):
    d_item = OR(deployment, "", "")

    # sha256 Hash is calculated over the DESIRED object
    c_item = d_item.annotate(canonicalize=False)
    assert three_way_diff_using_hash(c_item, d_item) is True


def test_3wpd_change_desired_should_apply(deployment):
    d_item = OR(deployment, "", "")
    c_item = d_item.annotate(canonicalize=False)

    del d_item.body["metadata"]["annotations"]
    assert three_way_diff_using_hash(c_item, d_item) is False


# Changes in current objects over attributes defined in desired
def test_3wpd_change_current_should_apply(deployment):
    d_item = OR(deployment, "", "")
    c_item = d_item.annotate(canonicalize=False)

    c_item.body["spec"]["replicas"] = 5
    assert three_way_diff_using_hash(c_item, d_item) is False


def test_is_a_cpu_mutation(deployment):
    patch = {
        "op": "replace",
        "path": "/spec/template/spec/containers/0/resources/requests/cpu",
        "value": "2000m",
    }
    deployment["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"][
        "cpu"
    ] = "2"
    current = OR(deployment, "", "")
    desired = OR(deployment, "", "")  # Not used to check cpu mutation
    assert is_cpu_mutation(current, desired, patch) is True


def test_is_not_a_cpu_mutation(deployment):
    patch = {
        "op": "replace",
        "path": "/spec/template/spec/containers/0/resources/requests/cpu",
        "value": "20m",
    }
    deployment["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"][
        "cpu"
    ] = "2"
    current = OR(deployment, "", "")
    desired = OR(deployment, "", "")  # Not used to check cpu mutation
    assert is_cpu_mutation(current, desired, patch) is False


def test_3wpd_change_valid_mutation_not_apply(deployment):
    d_item = OR(deployment, "", "")
    d_item.body["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"][
        "cpu"
    ] = "1000m"

    c_item = d_item.annotate(canonicalize=False)
    c_item.body["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"][
        "cpu"
    ] = "1"

    assert three_way_diff_using_hash(c_item, d_item) is True


def test_3wpd_change_empty_env_value_should_not_apply(deployment):
    d_item = OR(deployment, "", "")
    d_item.body["spec"]["template"]["spec"]["containers"][0]["env"] = [
        {
            "name": "test_env",
            "value": "",
        }
    ]

    c_item = d_item.annotate(canonicalize=False)
    c_item.body["spec"]["template"]["spec"]["containers"][0]["env"] = [
        {
            "name": "test_env",
        }
    ]

    assert three_way_diff_using_hash(c_item, d_item) is True
