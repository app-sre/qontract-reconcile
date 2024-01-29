import pytest
from pytest_mock import MockerFixture
from terrascript.resource import (
    aws_s3_bucket,
    aws_s3_bucket_notification,
    aws_s3_bucket_policy,
)

import reconcile.utils.terrascript_aws_client as tsclient
from reconcile.utils.aws_api import AmiTag
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceUniqueKey,
)


@pytest.fixture
def default_account():
    return {
        "automationToken": "token",
        "name": "account1",
        "providerVersion": "1.0.0",
        "resourcesDefaultRegion": "us-east-1",
        "supportedDeploymentRegions": ["us-east-1"],
        "terraformState": {
            "provider": "s3",
            "bucket": "some-bucket",
            "region": "us-east-1",
            "integrations": [
                {
                    "integration": "a-integration",
                    "key": "some-key",
                }
            ],
        },
        "uid": "12345",
    }


@pytest.fixture
def cluster_account():
    return {
        "automationToken": "token",
        "name": "account2",
        "providerVersion": "1.0.0",
        "resourcesDefaultRegion": "us-west-1",
        "supportedDeploymentRegions": ["us-west-1"],
        "terraformState": {
            "provider": "s3",
            "bucket": "cluster-account-bucket",
            "region": "us-west-1",
            "integrations": [
                {
                    "integration": "a-integration",
                    "key": "some-key",
                }
            ],
        },
        "uid": "67890",
    }


@pytest.fixture
def expected_supported_region_aws_provider():
    return {
        "access_key": "some-key-id",
        "secret_key": "some-secret-key",
        "version": "1.0.0",
        "region": "us-east-1",
        "alias": "us-east-1",
        "skip_region_validation": True,
        "default_tags": {
            "tags": {
                "app": "app-sre-infra",
            }
        },
    }


@pytest.fixture
def expected_default_region_aws_provider():
    return {
        "access_key": "some-key-id",
        "secret_key": "some-secret-key",
        "version": "1.0.0",
        "region": "us-east-1",
        "skip_region_validation": True,
        "default_tags": {
            "tags": {
                "app": "app-sre-infra",
            }
        },
    }


def test_init_with_default_tags(
    mocker,
    default_account,
    expected_supported_region_aws_provider,
    expected_default_region_aws_provider,
):
    mocked_secret_reader = mocker.patch(
        "reconcile.utils.terrascript_aws_client.SecretReader",
        autospec=True,
    )
    mocked_secret_reader.return_value.read_all.return_value = {
        "aws_access_key_id": "some-key-id",
        "aws_secret_access_key": "some-secret-key",
    }

    ts = tsclient.TerrascriptClient(
        "a_integration",
        "prefix",
        1,
        [default_account],
    )

    assert ts.tss["account1"]["provider"]["aws"] == [
        expected_supported_region_aws_provider,
        expected_default_region_aws_provider,
    ]


@pytest.fixture
def account_with_assume_role(default_account):
    return {
        **default_account,
        "assume_role": "arn:aws:iam::12345:role/1",
        "assume_region": "us-east-1",
    }


@pytest.fixture
def cluster_account_no_assume_role(cluster_account):
    return {
        **cluster_account,
        "assume_role": None,
        "assume_region": cluster_account["resourcesDefaultRegion"],
    }


@pytest.fixture
def expected_additional_aws_providers():
    return [
        {
            "access_key": "some-key-id",
            "alias": "account-12345-1",
            "assume_role": {"role_arn": "arn:aws:iam::12345:role/1"},
            "default_tags": {"tags": {"app": "app-sre-infra"}},
            "region": "us-east-1",
            "secret_key": "some-secret-key",
            "skip_region_validation": True,
            "version": "1.0.0",
        },
        {
            "access_key": "some-key-id",
            "alias": "account-account2-us-west-1",
            "default_tags": {"tags": {"app": "app-sre-infra"}},
            "region": "us-west-1",
            "secret_key": "some-secret-key",
            "skip_region_validation": True,
            "version": "1.0.0",
        },
    ]


def test_populate_additional_providers(
    mocker,
    default_account,
    account_with_assume_role,
    cluster_account_no_assume_role,
    expected_supported_region_aws_provider,
    expected_default_region_aws_provider,
    expected_additional_aws_providers,
):
    mocked_secret_reader = mocker.patch(
        "reconcile.utils.terrascript_aws_client.SecretReader",
        autospec=True,
    )
    mocked_secret_reader.return_value.read_all.return_value = {
        "aws_access_key_id": "some-key-id",
        "aws_secret_access_key": "some-secret-key",
    }

    ts = tsclient.TerrascriptClient(
        "a_integration",
        "prefix",
        1,
        [default_account],
    )
    ts.populate_configs([cluster_account_no_assume_role])
    ts.populate_additional_providers(
        default_account["name"],
        [account_with_assume_role, cluster_account_no_assume_role],
    )

    assert ts.tss["account1"]["provider"]["aws"] == [
        expected_supported_region_aws_provider,
        expected_default_region_aws_provider,
        *expected_additional_aws_providers,
    ]


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
    with awsapi() as aws:
        get_image_id_mock = aws.get_image_id
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


class MockProjectCommit:
    def __init__(self, id):
        setattr(self, "id", id)


@pytest.mark.parametrize(
    "repo_info, expected",
    [
        ({"url": "http://fake", "ref": 40 * "1"}, 40 * "1"),
        ({"url": "http://github.com/foo/bar", "ref": "main"}, "sha-12345"),
        (
            {"url": "http://gitlab.com/foo/bar", "ref": "master"},
            "sha-67890",
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
    init_gitlab = mocker.patch(
        "reconcile.utils.terrascript_aws_client.TerrascriptClient.init_gitlab"
    )
    init_gitlab.return_value.get_project.return_value.commits.list.return_value = [
        MockProjectCommit(expected)
    ]
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


def build_s3_spec(
    resource: dict,
) -> ExternalResourceSpec:
    provider = "aws"
    provisioner = {"name": "a"}
    namespace = {
        "name": "n",
        "managedExternalResources": True,
        "externalResources": [
            {
                "provider": provider,
                "provisioner": provisioner,
                "resources": [resource],
            },
        ],
        "cluster": {"name": "c"},
        "environment": {
            "name": "e",
        },
        "app": {"name": "app"},
    }
    return ExternalResourceSpec(
        provision_provider=provider,
        provisioner=provisioner,
        resource=resource,
        namespace=namespace,
    )


@pytest.fixture
def s3_default_spec() -> ExternalResourceSpec:
    resource = {
        "identifier": "s3-bucket",
        "provider": "s3",
    }
    return build_s3_spec(resource)


@pytest.fixture
def expected_s3_default_bucket() -> aws_s3_bucket:
    return aws_s3_bucket(
        "s3-bucket",
        **{
            "bucket": "s3-bucket",
            "versioning": {"enabled": True},
            "tags": {
                "managed_by_integration": "",
                "cluster": "c",
                "namespace": "n",
                "environment": "e",
                "app": "app",
            },
            "lifecycle": {"ignore_changes": ["grant"]},
            "server_side_encryption_configuration": {
                "rule": {
                    "apply_server_side_encryption_by_default": {
                        "sse_algorithm": "AES256"
                    }
                }
            },
        },
    )


def test_populate_tf_resource_s3(
    ts: tsclient.TerrascriptClient,
    s3_default_spec: ExternalResourceSpec,
    expected_s3_default_bucket: aws_s3_bucket,
) -> None:
    bucket_tf_resource = ts.populate_tf_resource_s3(s3_default_spec)

    assert bucket_tf_resource == expected_s3_default_bucket


@pytest.fixture
def s3_spec_with_bucket_policy() -> ExternalResourceSpec:
    resource = {
        "identifier": "s3-bucket",
        "provider": "s3",
        "bucket_policy": "some-bucket-policy",
    }
    return build_s3_spec(resource)


@pytest.fixture
def expected_s3_bucket_policy() -> aws_s3_bucket_policy:
    return aws_s3_bucket_policy(
        "s3-bucket",
        **{
            "bucket": "s3-bucket",
            "policy": "some-bucket-policy",
            "depends_on": ["aws_s3_bucket.s3-bucket"],
        },
    )


def test_populate_tf_resource_s3_with_bucket_policy(
    mocker: MockerFixture,
    ts: tsclient.TerrascriptClient,
    s3_spec_with_bucket_policy: ExternalResourceSpec,
    expected_s3_default_bucket: aws_s3_bucket,
    expected_s3_bucket_policy: aws_s3_bucket_policy,
) -> None:
    mocked_add_resources = mocker.patch.object(ts, "add_resources")

    bucket_tf_resource = ts.populate_tf_resource_s3(s3_spec_with_bucket_policy)

    assert bucket_tf_resource == expected_s3_default_bucket

    mocked_add_resources.assert_called_once()
    identifier, tf_resources = mocked_add_resources.call_args.args
    assert identifier == "a"
    assert expected_s3_bucket_policy in tf_resources


@pytest.fixture
def s3_spec_with_bucket_policy_and_region() -> ExternalResourceSpec:
    resource = {
        "identifier": "s3-bucket",
        "provider": "s3",
        "bucket_policy": "some-bucket-policy",
        "region": "us-west-2",
    }
    return build_s3_spec(resource)


@pytest.fixture
def expected_s3_bucket_with_region() -> aws_s3_bucket:
    return aws_s3_bucket(
        "s3-bucket",
        **{
            "bucket": "s3-bucket",
            "versioning": {"enabled": True},
            "tags": {
                "managed_by_integration": "",
                "cluster": "c",
                "namespace": "n",
                "environment": "e",
                "app": "app",
            },
            "lifecycle": {"ignore_changes": ["grant"]},
            "server_side_encryption_configuration": {
                "rule": {
                    "apply_server_side_encryption_by_default": {
                        "sse_algorithm": "AES256"
                    }
                }
            },
            "provider": "aws.us-west-2",
        },
    )


@pytest.fixture
def expected_s3_bucket_policy_with_region() -> aws_s3_bucket_policy:
    return aws_s3_bucket_policy(
        "s3-bucket",
        **{
            "bucket": "s3-bucket",
            "policy": "some-bucket-policy",
            "depends_on": ["aws_s3_bucket.s3-bucket"],
            "provider": "aws.us-west-2",
        },
    )


def test_populate_tf_resource_s3_with_bucket_policy_and_different_region(
    mocker: MockerFixture,
    ts: tsclient.TerrascriptClient,
    s3_spec_with_bucket_policy_and_region: ExternalResourceSpec,
    expected_s3_bucket_with_region: aws_s3_bucket,
    expected_s3_bucket_policy_with_region: aws_s3_bucket_policy,
) -> None:
    mocked_add_resources = mocker.patch.object(ts, "add_resources")
    mocker.patch.object(ts, "_multiregion_account", return_value=True)

    bucket_tf_resource = ts.populate_tf_resource_s3(
        s3_spec_with_bucket_policy_and_region
    )

    assert bucket_tf_resource == expected_s3_bucket_with_region

    mocked_add_resources.assert_called_once()
    identifier, tf_resources = mocked_add_resources.call_args.args
    assert identifier == "a"
    assert expected_s3_bucket_policy_with_region in tf_resources


@pytest.fixture()
def s3_spec_with_event_notifications() -> ExternalResourceSpec:
    resource = {
        "identifier": "s3-bucket",
        "provider": "s3",
        "event_notifications": [
            {
                "destination_type": "sqs",
                "destination": "test-sqs",
                "event_type": ["s3:ObjectCreated:*"],
            }
        ],
        "region": "us-west-2",
    }
    return build_s3_spec(resource)


@pytest.fixture()
def expected_s3_bucket_notification() -> aws_s3_bucket_notification:
    return aws_s3_bucket_notification(
        "s3-bucket-event-notifications",
        **{
            "bucket": "${aws_s3_bucket.s3-bucket.id}",
            "queue": [
                {
                    "id": "test-sqs",
                    "queue_arn": "${data.aws_sqs_queue.test-sqs.arn}",
                    "events": ["s3:ObjectCreated:*"],
                }
            ],
        },
    )


def test_s3_bucket_event_notifications(
    mocker: MockerFixture,
    ts: tsclient.TerrascriptClient,
    s3_spec_with_event_notifications: ExternalResourceSpec,
    expected_s3_bucket_notification: aws_s3_bucket_notification,
) -> None:
    mocked_add_resources = mocker.patch.object(ts, "add_resources")
    mocker.patch.object(ts, "_multiregion_account", return_value=True)

    ts.populate_tf_resource_s3(s3_spec_with_event_notifications)

    mocked_add_resources.assert_called_once()
    identifier, tf_resources = mocked_add_resources.call_args.args
    assert identifier == "a"
    assert expected_s3_bucket_notification in tf_resources


def test_get_resource_lifecycle_none(
    ts: tsclient.TerrascriptClient,
) -> None:
    common_values = {"lifecycle": None}
    lifecycle = ts.get_resource_lifecycle(common_values)
    assert lifecycle is None


def test_get_resource_lifecycle_default(
    ts: tsclient.TerrascriptClient,
) -> None:
    common_values: dict = {
        "lifecycle": {
            "create_before_destroy": None,
            "prevent_destroy": None,
            "ignore_changes": [],
        }
    }
    lifecycle = ts.get_resource_lifecycle(common_values)
    expected = {
        "create_before_destroy": False,
        "prevent_destroy": False,
        "ignore_changes": [],
    }
    assert lifecycle == expected


def test_get_resource_lifecycle_all(
    ts: tsclient.TerrascriptClient,
) -> None:
    common_values: dict = {
        "lifecycle": {
            "create_before_destroy": None,
            "prevent_destroy": None,
            "ignore_changes": ["all"],
        }
    }
    lifecycle = ts.get_resource_lifecycle(common_values)
    expected = {
        "create_before_destroy": False,
        "prevent_destroy": False,
        "ignore_changes": "all",
    }
    assert lifecycle == expected
