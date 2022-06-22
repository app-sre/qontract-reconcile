import pytest

import reconcile.utils.terrascript_aws_client as tsclient


def test_sanitize_resource_with_dots():
    assert tsclient.safe_resource_id("foo.example.com") == "foo_example_com"


def test_sanitize_resource_with_wildcard():
    assert tsclient.safe_resource_id("*.foo.example.com") == "_star_foo_example_com"


@pytest.fixture
def ts():
    return tsclient.TerrascriptClient("", "", 1, [])


def test_aws_username_org(ts):
    result = "org"
    user = {"org_username": result}
    assert ts._get_aws_username(user) == result


def test_aws_username_aws(ts):
    result = "aws"
    user = {"org_username": "org", "aws_username": result}
    assert ts._get_aws_username(user) == result


def test_validate_mandatory_policies(ts):
    mandatory_policy = {
        "name": "mandatory",
        "mandatory": True,
    }
    not_mandatory_policy = {
        "name": "not-mandatory",
    }
    account = {"name": "acc", "policies": [mandatory_policy, not_mandatory_policy]}
    assert ts._validate_mandatory_policies(account, [mandatory_policy], "role") is True
    assert (
        ts._validate_mandatory_policies(account, [not_mandatory_policy], "role")
        is False
    )


class MockJenkinsApi:
    def __init__(self, response):
        self.response = response

    def is_job_running(self, name):
        return self.response


def test_use_previous_image_id_no_upstream(ts):
    assert ts._use_previous_image_id({}) is False


def test_use_previous_image_id_false(mocker, ts):
    result = False
    mocker.patch(
        "reconcile.utils.terrascript_aws_client.TerrascriptClient.init_jenkins",
        return_value=MockJenkinsApi(result),
    )
    image = {"upstream": {"instance": {"name": "ci"}, "name": "job"}}
    assert ts._use_previous_image_id(image) == result


def test_use_previous_image_id_true(mocker, ts):
    result = True
    mocker.patch(
        "reconcile.utils.terrascript_aws_client.TerrascriptClient.init_jenkins",
        return_value=MockJenkinsApi(result),
    )
    image = {"upstream": {"instance": {"name": "ci"}, "name": "job"}}
    assert ts._use_previous_image_id(image) == result
