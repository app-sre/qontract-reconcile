import pytest
from reconcile.utils.aws_api import AmiTag

import reconcile.utils.terrascript_aws_client as tsclient
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceUniqueKey,
)


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
    assert ts._use_previous_image_id([]) is False


@pytest.mark.parametrize("result", [True, False])
def test_use_previous_image_id(mocker, ts, result):
    mocker.patch(
        "reconcile.utils.terrascript_aws_client.TerrascriptClient.init_jenkins",
        return_value=MockJenkinsApi(result),
    )
    image = [{"upstream": {"instance": {"name": "ci"}, "name": "job"}}]
    assert ts._use_previous_image_id(image) == result


def test_get_asg_image_id(mocker, ts: tsclient.TerrascriptClient):
    awsapi = mocker.patch("reconcile.utils.terrascript_aws_client.AWSApi")
    get_image_id_mock = awsapi().get_image_id
    get_image_id_mock.return_value = "ami-123456"

    ref = "sha-12345"
    mocker.patch(
        "reconcile.utils.terrascript_aws_client.TerrascriptClient.get_commit_sha",
        return_value=ref,
    )
    ts.accounts["some-account"] = "mock"  # type: ignore
    image_id = ts.get_asg_image_id(
        filters=[
            {"provider": "git", "tag_name": "commit", "ref": ref},
            {
                "provider": "static",
                "tag_name": "tag1",
                "value": "value1",
            },
            {
                "provider": "static",
                "tag_name": "tag2",
                "value": "value2",
            },
        ],
        account="some-account",
        region="us-east-1",
    )
    assert image_id == "ami-123456"
    get_image_id_mock.assert_called_with(
        "some-account",
        "us-east-1",
        [
            AmiTag(name="commit", value=ref),
            AmiTag(name="tag1", value="value1"),
            AmiTag(name="tag2", value="value2"),
        ],
    )


@pytest.mark.parametrize(
    "repo_info, expected",
    [
        ({"url": "http://fake", "ref": 40 * "1"}, 40 * "1"),
        ({"url": "http://github.com/foo/bar", "ref": "main"}, "sha-12345"),
        pytest.param(
            {"url": "http://gitlab.com/foo/bar", "ref": "main"},
            "",
            marks=pytest.mark.xfail(raises=NotImplementedError, strict=True),
        ),
    ],
)
def test_get_commit_sha(mocker, ts: tsclient.TerrascriptClient, repo_info, expected):
    init_github = mocker.patch(
        "reconcile.utils.terrascript_aws_client.TerrascriptClient.init_github"
    )
    init_github.return_value.get_repo.return_value.get_commit.return_value.sha = (
        expected
    )
    assert ts.get_commit_sha(repo_info) == expected


def test_tf_disabled_namespace_with_resources(ts):
    """
    even if a namespace has tf resources, they are not considered when the
    namespace is not enabled for tf resource management
    """
    ra = {"identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": False,
        "externalResources": [
            {"provider": "aws", "provisioner": {"name": "a"}, "resources": [ra]}
        ],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1]
    ts.init_populate_specs(namespaces, None)
    specs = ts.resource_spec_inventory
    assert not specs


def test_resource_specs_without_account_filter(ts):
    """
    if no account filter is given, all resources of namespaces with
    enabled tf resource management are expected to be returned
    """
    p = "aws"
    pa = {"name": "a"}
    ra = {"identifier": "a", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [{"provider": p, "provisioner": pa, "resources": [ra]}],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1]
    ts.init_populate_specs(namespaces, None)
    specs = ts.resource_spec_inventory
    spec = ExternalResourceSpec(p, pa, ra, ns1)
    assert specs == {ExternalResourceUniqueKey.from_spec(spec): spec}


def test_resource_specs_with_account_filter(ts):
    """
    if an account filter is given only the resources defined for
    that account are expected
    """
    p = "aws"
    pa = {"name": "a"}
    ra = {"identifier": "a", "provider": "p"}
    pb = {"name": "b"}
    rb = {"identifier": "b", "provider": "p"}
    ns1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {"provider": p, "provisioner": pa, "resources": [ra]},
            {"provider": p, "provisioner": pb, "resources": [rb]},
        ],
        "cluster": {"name": "c"},
    }
    namespaces = [ns1]
    ts.init_populate_specs(namespaces, "a")
    specs = ts.resource_spec_inventory
    spec = ExternalResourceSpec(p, pa, ra, ns1)
    assert specs == {ExternalResourceUniqueKey.from_spec(spec): spec}


expected_result = {
    "s3": {
        "access_key": "SOMEKEY123",
        "secret_key": "somesecretkey",
        "bucket": "some-bucket",
        "key": "qontract-reconcile.tfstate",
        "region": "us-east-1",
    }
}


def test_terraform_state_when_present(ts):
    account_name = "some-account"
    integration_name = "terraform-resources-wrapper"
    terraform_state_config_test = {
        "aws_access_key_id": "SOMEKEY123",
        "aws_secret_access_key": "somesecretkey",
        "bucket": "some-bucket",
        "key": "qontract-reconcile.tfstate",
        "region": "us-east-1",
        "terraform-resources-wrapper_key": "qontract-reconcile.tfstate",
        "terraformState": {
            "provider": "s3",
            "bucket": "some-bucket",
            "region": "some-region",
            "integrations": [
                {
                    "key": "terraform-resources-wrapper",
                    "integration": "qontract-reconcile.tfstate",
                },
            ],
        },
    }
    assert (
        ts.state_bucket_for_account(
            integration_name, account_name, terraform_state_config_test
        )
        == expected_result
    )


terraform_state_config_test_missing = {
    "aws_access_key_id": "SOMEKEY123",
    "aws_secret_access_key": "somesecretkey",
    "bucket": "some-bucket",
    "key": "qontract-reconcile.tfstate",
    "region": "us-east-1",
    "terraform-resources-wrapper_key": "qontract-reconcile.tfstate",
    "terraformState": None,
}


def test_terraform_state_when_not_present(ts):
    account_name = "some-account"
    integration_name = "terraform-resources-wrapper"
    assert (
        ts.state_bucket_for_account(
            integration_name, account_name, terraform_state_config_test_missing
        )
        == expected_result
    )


def test_terraform_state_when_not_present_error(ts):
    account_name = "some-account"
    integration_name = "not-found-integration"
    try:
        ts.state_bucket_for_account(
            integration_name, account_name, terraform_state_config_test_missing
        )
    except ValueError:
        pass
