import contextlib
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture
from terrascript.resource import (
    aws_lb,
    aws_s3_bucket,
    aws_s3_bucket_notification,
    aws_s3_bucket_policy,
)

from reconcile.utils.aws_api import AmiTag
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceUniqueKey,
)
from reconcile.utils.ocm.ocm import OCM
from reconcile.utils.terrascript_aws_client import (
    OutputResourceNameNotUniqueError,
    ProviderExcludedError,
    TerrascriptClient,
)


@pytest.fixture
def default_account() -> dict[str, Any]:
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
def cluster_account() -> dict[str, Any]:
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
def expected_supported_region_aws_provider() -> dict[str, Any]:
    return {
        "access_key": "some-key-id",
        "secret_key": "some-secret-key",
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
def expected_default_region_aws_provider() -> dict[str, Any]:
    return {
        "access_key": "some-key-id",
        "secret_key": "some-secret-key",
        "region": "us-east-1",
        "skip_region_validation": True,
        "default_tags": {
            "tags": {
                "app": "app-sre-infra",
            }
        },
    }


def test_init_with_default_tags(
    mocker: MockerFixture, default_account: dict[str, Any]
) -> None:
    mocked_secret_reader = mocker.patch(
        "reconcile.utils.terrascript_aws_client.SecretReader",
        autospec=True,
    )
    mocked_secret_reader.return_value.read_all.return_value = {
        "aws_access_key_id": "some-key-id",
        "aws_secret_access_key": "some-secret-key",
    }

    default_tags = {"tag1": "value1", "tag2": "value2"}
    ts = TerrascriptClient(
        "a_integration",
        "prefix",
        1,
        [default_account],
        default_tags=default_tags,
    )

    assert ts.tss["account1"]["provider"]["aws"] == [
        {
            "access_key": "some-key-id",
            "secret_key": "some-secret-key",
            "region": "us-east-1",
            "alias": "us-east-1",
            "skip_region_validation": True,
            "default_tags": {"tags": default_tags},
        },
        {
            "access_key": "some-key-id",
            "secret_key": "some-secret-key",
            "region": "us-east-1",
            "skip_region_validation": True,
            "default_tags": {"tags": default_tags},
        },
    ]


@pytest.fixture
def account_with_assume_role(default_account: dict[str, Any]) -> dict[str, Any]:
    return {
        **default_account,
        "assume_role": "arn:aws:iam::12345:role/1",
        "assume_region": "us-east-1",
    }


@pytest.fixture
def cluster_account_no_assume_role(cluster_account: dict[str, Any]) -> dict[str, Any]:
    return {
        **cluster_account,
        "assume_role": None,
        "assume_region": cluster_account["resourcesDefaultRegion"],
    }


@pytest.fixture
def expected_additional_aws_providers() -> list[dict[str, Any]]:
    return [
        {
            "access_key": "some-key-id",
            "alias": "account-12345-1",
            "assume_role": {"role_arn": "arn:aws:iam::12345:role/1"},
            "default_tags": {"tags": {"app": "app-sre-infra"}},
            "region": "us-east-1",
            "secret_key": "some-secret-key",
            "skip_region_validation": True,
        },
        {
            "access_key": "some-key-id",
            "alias": "account-account2-us-west-1",
            "default_tags": {"tags": {"app": "app-sre-infra"}},
            "region": "us-west-1",
            "secret_key": "some-secret-key",
            "skip_region_validation": True,
        },
    ]


@pytest.fixture
def mock_provider_exclusions_by_provider(mocker: MockerFixture) -> None:
    mock = mocker.patch(
        "reconcile.queries.get_tf_resources_provider_exclusions_by_provisioner",
        autospec=True,
    )
    mock.return_value = []


def test_populate_additional_providers(
    mocker: MockerFixture,
    default_account: dict[str, Any],
    account_with_assume_role: dict[str, Any],
    cluster_account_no_assume_role: dict[str, Any],
    expected_supported_region_aws_provider: dict[str, Any],
    expected_default_region_aws_provider: dict[str, Any],
    expected_additional_aws_providers: dict[str, Any],
) -> None:
    mocked_secret_reader = mocker.patch(
        "reconcile.utils.terrascript_aws_client.SecretReader",
        autospec=True,
    )
    mocked_secret_reader.return_value.read_all.return_value = {
        "aws_access_key_id": "some-key-id",
        "aws_secret_access_key": "some-secret-key",
    }

    ts = TerrascriptClient(
        "a_integration",
        "prefix",
        1,
        [default_account],
        default_tags=None,
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
def ts() -> TerrascriptClient:
    return TerrascriptClient("", "", 1, [], default_tags=None)


def test_aws_username_org(ts: TerrascriptClient) -> None:
    result = "org"
    user = {"org_username": result}
    assert ts._get_aws_username(user) == result


def test_aws_username_aws(ts: TerrascriptClient) -> None:
    result = "aws"
    user = {"org_username": "org", "aws_username": result}
    assert ts._get_aws_username(user) == result


def test_validate_mandatory_policies(ts: TerrascriptClient) -> None:
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
    def __init__(self, response: bool) -> None:
        self.response = response

    def is_job_running(self, name: str) -> bool:
        return self.response


def test_use_previous_image_id_no_upstream(ts: TerrascriptClient) -> None:
    assert ts._use_previous_image_id([]) is False


@pytest.mark.parametrize("result", [True, False])
def test_use_previous_image_id(
    mocker: MockerFixture, ts: TerrascriptClient, result: bool
) -> None:
    mocker.patch(
        "reconcile.utils.terrascript_aws_client.TerrascriptClient.init_jenkins",
        return_value=MockJenkinsApi(result),
    )
    image = [{"upstream": {"instance": {"name": "ci"}, "name": "job"}}]
    assert ts._use_previous_image_id(image) == result


def test_get_asg_image_id(mocker: MockerFixture, ts: TerrascriptClient) -> None:
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


@dataclass
class MockProjectCommit:
    id: str


@pytest.mark.parametrize(
    "repo_info, expected",
    [
        ({"url": "http://fake", "ref": 40 * "1"}, 40 * "1"),
        ({"url": "https://github.com/foo/bar", "ref": "main"}, "sha-12345"),
        (
            {"url": "http://gitlab.com/foo/bar", "ref": "master"},
            "sha-67890",
        ),
    ],
)
def test_get_commit_sha(
    mocker: MockerFixture,
    ts: TerrascriptClient,
    repo_info: dict[str, str],
    expected: str,
) -> None:
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


def test_tf_disabled_namespace_with_resources(
    mock_provider_exclusions_by_provider: None, ts: TerrascriptClient
) -> None:
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


def test_resource_specs_without_account_filter(
    mock_provider_exclusions_by_provider: None, ts: TerrascriptClient
) -> None:
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


def test_resource_specs_with_account_filter(
    mock_provider_exclusions_by_provider: None, ts: TerrascriptClient
) -> None:
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


def test_terraform_state_when_present(ts: TerrascriptClient) -> None:
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


def test_terraform_state_when_not_present(ts: TerrascriptClient) -> None:
    account_name = "some-account"
    integration_name = "terraform-resources-wrapper"
    assert (
        ts.state_bucket_for_account(
            integration_name, account_name, terraform_state_config_test_missing
        )
        == expected_result
    )


def test_terraform_state_when_not_present_error(ts: TerrascriptClient) -> None:
    account_name = "some-account"
    integration_name = "not-found-integration"
    with contextlib.suppress(ValueError):
        ts.state_bucket_for_account(
            integration_name, account_name, terraform_state_config_test_missing
        )


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
    resource = {"identifier": "s3-bucket", "provider": "s3", "region": "us-east-1"}
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
    ts: TerrascriptClient,
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
        "region": "us-east-1",
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
    ts: TerrascriptClient,
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
    ts: TerrascriptClient,
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
    ts: TerrascriptClient,
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


@pytest.fixture
def ts_for_alb(mocker: MockerFixture) -> TerrascriptClient:
    mock_awsh = mocker.patch("reconcile.utils.terrascript_aws_client.awsh")
    mock_awsh.get_tf_secrets.return_value = (
        "a",
        {
            "aws_access_key_id": "TOTALLYRANDOMKEYID",
            "aws_provider_version'": "3.22.0",
            "aws_secret_access_key": "even_more_random_string_key",
            "key": "qontract-reconcile.tfstate",
        },
    )
    mock_awsh.get_account.return_value = {
        "resourcesDefaultRegion": "us-east-1",
        "supportedDeploymentRegions": ["us-east-1", "us-east-2"],
        "terraformState": {
            "provider": "s3",
            "bucket": "test-state-bucket",
            "region": "us-east-1",
            "integrations": [
                {
                    "key": "qontract-reconcile.tfstate",
                    "integration": "terraform-resources",
                }
            ],
        },
    }

    return TerrascriptClient(
        integration="terraform_resources",
        integration_prefix="qrtf",
        thread_pool_size=1,
        accounts=[
            {
                "terraformUsername": "terraform",
                "uid": "0123456789012",
                "name": "a",
                "automationToken": {
                    "path": "some/path",
                    "field": "all",
                },
                "providerVersion": "5.39.1",
                "resourcesDefaultRegion": "us-east-1",
            }
        ],
        default_tags=None,
    )


def build_alb_spec(
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
        "cluster": {"name": "c", "spec": {"region": "us-east-1"}},
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


@pytest.fixture()
def alb_spec() -> ExternalResourceSpec:
    alb_spec = {
        "identifier": "alb-resource",
        "provider": "alb",
        "vpc": {
            "vpc_id": "vpc-id",
            "cidr_block": "10.0.0.1/16",
            "subnets": [{"id": "subnet-id-1"}, {"id": "subnet-id-2"}],
        },
        "ingress_cidr_blocks": ["0.0.0.0/0"],
        "certificate_arn": "arn:aws:acm:us-east-1:0123456789012:certificate/some-uid",
        "targets": [
            {
                "name": "registry-proxy-stage",
                "default": False,
                "openshift_service": "registry-proxy-stage",
                "protocol": "HTTP",
            },
            {
                "name": "registry-proxy-https",
                "default": True,
                "openshift_service": "registry-proxy-stage",
                "protocol": "HTTPS",
            },
            {
                "name": "registry-proxy-pull",
                "default": False,
                "openshift_service": "registry-proxy-stage",
            },
        ],
        "rules": [
            {
                "condition": [{"type": "path-pattern", "path_pattern": ["/"]}],
                "action": {
                    "type": "redirect",
                    "redirect": {
                        "host": "example.com",
                        "status_code": "HTTP_301",
                    },
                },
            },
            {
                "condition": [{"type": "path-pattern", "path_pattern": ["/metrics"]}],
                "action": {
                    "type": "fixed-response",
                    "fixed_response": {
                        "status_code": 401,
                        "content_type": "application/json",
                        "message_body": '{"errors":[{"code":"UNAUTHORIZED","detail":{},"message":"access to the requested resource is not authorized"}]}',
                    },
                },
            },
        ],
    }

    return build_alb_spec(alb_spec)


@pytest.fixture()
def expected_alb_resource() -> aws_lb:
    return aws_lb(
        "alb-resource",
        **{
            "depends_on": ["aws_security_group.alb-resource"],
            "internal": False,
            "ip_address_type": "ipv4",
            "load_balancer_type": "application",
            "name": "alb-resource",
            "provider": "aws.us-east-1",
            "security_groups": ["${aws_security_group.alb-resource.id}"],
            "subnets": ["subnet-id-1", "subnet-id-2"],
            "tags": {
                "managed_by_integration": "terraform_resources",
                "cluster": "c",
                "namespace": "n",
                "environment": "e",
                "app": "app",
            },
        },
    )


@pytest.fixture()
def mock_alb_setup(mocker: MockerFixture) -> MagicMock:
    mock_awsapi = mocker.patch("reconcile.utils.terrascript_aws_client.AWSApi")
    mock_awsapi.get_alb_network_interface_ips.return_value = {
        "10.0.0.1",
        "10.0.0.2",
        "10.0.0.3",
    }

    ocm_mock = mocker.patch.object(
        OCM,
        "get_aws_infrastructure_access_terraform_assume_role",
        autospec=True,
    )
    ocm_mock.return_value = "arn:aws:iam::0123456789012:role/network-mgmt-2tgm4m"
    ocmmap_mock = MagicMock()
    ocmmap_mock.__getitem__.return_value = ocm_mock

    return ocmmap_mock


def test_populate_tf_resource_alb(
    mocker: MockerFixture,
    ts_for_alb: TerrascriptClient,
    alb_spec: ExternalResourceSpec,
    expected_alb_resource: aws_lb,
    mock_alb_setup: MagicMock,
) -> None:
    mocked_add_resources = mocker.patch.object(ts_for_alb, "add_resources")
    mocker.patch.object(ts_for_alb, "_multiregion_account", return_value=True)

    ts_for_alb.populate_tf_resource_alb(spec=alb_spec, ocm_map=mock_alb_setup)

    mocked_add_resources.assert_called_once()
    identifier, tf_resources = mocked_add_resources.call_args.args
    assert identifier == "a"
    assert expected_alb_resource in tf_resources


def test_get_resource_lifecycle_none(
    ts: TerrascriptClient,
) -> None:
    common_values = {"lifecycle": None}
    lifecycle = ts.get_resource_lifecycle(common_values)
    assert lifecycle is None


def test_get_resource_lifecycle_default(
    ts: TerrascriptClient,
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
    ts: TerrascriptClient,
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


def test_output_resource_name_not_unique_raises_exception(
    mock_provider_exclusions_by_provider: None, ts: TerrascriptClient
) -> None:
    external_resource_1 = {
        "identifier": "a",
        "provider": "rds",
        "output_resource_name": "oa",
    }
    external_resource_2 = {
        "identifier": "b",
        "provider": "rds",
        "output_resource_name": "oa",
    }
    namespace_1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {
                "provider": "aws",
                "provisioner": {"name": "a"},
                "resources": [external_resource_1, external_resource_2],
            }
        ],
        "cluster": {"name": "test"},
    }
    namespaces = [namespace_1]

    with pytest.raises(OutputResourceNameNotUniqueError):
        ts.init_populate_specs(namespaces, "account")


def test_output_resource_name_unique_success(
    mock_provider_exclusions_by_provider: None, ts: TerrascriptClient
) -> None:
    external_resource_1 = {
        "identifier": "a",
        "provider": "rds",
        "output_resource_name": "oa",
    }
    external_resource_2 = {
        "identifier": "b",
        "provider": "rds",
        "output_resource_name": "ob",
    }
    namespace_1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {
                "provider": "aws",
                "provisioner": {"name": "a"},
                "resources": [external_resource_1, external_resource_2],
            }
        ],
        "cluster": {"name": "test"},
    }
    namespaces = [namespace_1]

    ts.init_populate_specs(namespaces, "account")


def test_managed_by_erv2_is_excluded(
    mock_provider_exclusions_by_provider: None, ts: TerrascriptClient
) -> None:
    external_resource_1 = {
        "identifier": "a",
        "managed_by_erv2": True,
        "provider": "rds",
        "output_resource_name": "oa",
    }
    external_resource_2 = {
        "identifier": "b",
        "provider": "rds",
        "output_resource_name": "ob",
    }
    namespace_1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {
                "provider": "aws",
                "provisioner": {"name": "a"},
                "resources": [external_resource_1, external_resource_2],
            }
        ],
        "cluster": {"name": "test"},
    }
    namespaces = [namespace_1]

    ts.init_populate_specs(namespaces, "account")
    assert len(ts.resource_spec_inventory) == 1


def test_excluded_provider_throws_exception(
    mocker: MockerFixture, ts: TerrascriptClient
) -> None:
    external_resource_1 = {
        "identifier": "a",
        "provider": "rds",
        "output_resource_name": "oa",
    }
    external_resource_2 = {
        "identifier": "b",
        "provider": "rds",
        "output_resource_name": "ob",
    }
    namespace_1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {
                "provider": "aws",
                "provisioner": {"name": "a"},
                "resources": [external_resource_1, external_resource_2],
            }
        ],
        "cluster": {"name": "test"},
    }
    namespaces = [namespace_1]

    mock = mocker.patch(
        "reconcile.queries.get_tf_resources_provider_exclusions_by_provisioner",
        autospec=True,
    )
    mock.return_value = [{"provider": "rds", "excludeProvisioners": [{"name": "a"}]}]

    with pytest.raises(ProviderExcludedError):
        ts.init_populate_specs(namespaces, "account")


def test_exclude_all_provisioners_throws_exception(
    mocker: MockerFixture, ts: TerrascriptClient
) -> None:
    external_resource_1 = {
        "identifier": "a",
        "provider": "rds",
        "output_resource_name": "oa",
    }
    external_resource_2 = {
        "identifier": "b",
        "provider": "rds",
        "output_resource_name": "ob",
    }
    namespace_1 = {
        "name": "ns1",
        "managedExternalResources": True,
        "externalResources": [
            {
                "provider": "aws",
                "provisioner": {"name": "a"},
                "resources": [external_resource_1, external_resource_2],
            }
        ],
        "cluster": {"name": "test"},
    }
    namespaces = [namespace_1]

    mock = mocker.patch(
        "reconcile.queries.get_tf_resources_provider_exclusions_by_provisioner",
        autospec=True,
    )
    mock.return_value = [{"provider": "rds", "excludeAllProvisioners": True}]

    with pytest.raises(ProviderExcludedError):
        ts.init_populate_specs(namespaces, "account")


def test_get_alb_rule_condition_value_query_string(ts: TerrascriptClient) -> None:
    condition = {
        "type": "query-string",
        "query_string": [
            {"key": "version", "value": "v1"},
            {"key": "env", "value": "prod"},
        ],
    }
    result = ts._get_alb_rule_condition_value(condition)
    expected = {
        "query_string": [
            {"key": "version", "value": "v1"},
            {"key": "env", "value": "prod"},
        ]
    }
    assert result == expected


def test_get_alb_rule_condition_value_query_string_with_none_key(
    ts: TerrascriptClient,
) -> None:
    condition = {
        "type": "query-string",
        "query_string": [
            {"key": None, "value": "debug"},
            {"key": "version", "value": "v2"},
        ],
    }
    result = ts._get_alb_rule_condition_value(condition)
    expected = {
        "query_string": [
            {"key": None, "value": "debug"},
            {"key": "version", "value": "v2"},
        ]
    }
    assert result == expected


def test_get_alb_rule_condition_value_path_pattern(ts: TerrascriptClient) -> None:
    condition = {"type": "path-pattern", "path_pattern": ["/api/*", "/health"]}
    result = ts._get_alb_rule_condition_value(condition)
    expected = {"path_pattern": {"values": ["/api/*", "/health"]}}
    assert result == expected


def test_get_alb_rule_condition_value_unknown_type(ts: TerrascriptClient) -> None:
    condition = {"type": "unknown-type", "unknown_type": ["value"]}
    with pytest.raises(KeyError, match="unknown alb rule condition type unknown-type"):
        ts._get_alb_rule_condition_value(condition)


@pytest.fixture()
def alb_spec_with_query_string() -> ExternalResourceSpec:
    alb_spec = {
        "identifier": "alb-with-query-string",
        "provider": "alb",
        "vpc": {
            "vpc_id": "vpc-id",
            "cidr_block": "10.0.0.1/16",
            "subnets": [{"id": "subnet-id-1"}, {"id": "subnet-id-2"}],
        },
        "ingress_cidr_blocks": ["0.0.0.0/0"],
        "certificate_arn": "arn:aws:acm:us-east-1:0123456789012:certificate/some-uid",
        "targets": [
            {
                "name": "api-v1",
                "default": True,
                "openshift_service": "api-service",
                "protocol": "HTTP",
            }
        ],
        "rules": [
            {
                "condition": [
                    {
                        "type": "query-string",
                        "query_string": [
                            {"key": "version", "value": "v1"},
                            {"key": "env", "value": "prod"},
                        ],
                    }
                ],
                "action": {
                    "type": "forward",
                    "forward": {"target_group": [{"target": "api-v1", "weight": 100}]},
                },
            }
        ],
    }
    return build_alb_spec(alb_spec)


@pytest.fixture()
def alb_spec_with_query_string_none_key() -> ExternalResourceSpec:
    alb_spec = {
        "identifier": "alb-with-query-string-none-key",
        "provider": "alb",
        "vpc": {
            "vpc_id": "vpc-id",
            "cidr_block": "10.0.0.1/16",
            "subnets": [{"id": "subnet-id-1"}, {"id": "subnet-id-2"}],
        },
        "ingress_cidr_blocks": ["0.0.0.0/0"],
        "certificate_arn": "arn:aws:acm:us-east-1:0123456789012:certificate/some-uid",
        "targets": [
            {
                "name": "debug-target",
                "default": True,
                "openshift_service": "debug-service",
                "protocol": "HTTP",
            }
        ],
        "rules": [
            {
                "condition": [
                    {
                        "type": "query-string",
                        "query_string": [
                            {"key": None, "value": "debug"},
                            {"key": "version", "value": "v2"},
                        ],
                    }
                ],
                "action": {
                    "type": "forward",
                    "forward": {
                        "target_group": [{"target": "debug-target", "weight": 100}]
                    },
                },
            }
        ],
    }
    return build_alb_spec(alb_spec)


def test_populate_tf_resource_alb_with_query_string_condition(
    mocker: MockerFixture,
    ts_for_alb: TerrascriptClient,
    alb_spec_with_query_string: ExternalResourceSpec,
    mock_alb_setup: MagicMock,
) -> None:
    mocked_add_resources = mocker.patch.object(ts_for_alb, "add_resources")
    mocker.patch.object(ts_for_alb, "_multiregion_account", return_value=True)

    ts_for_alb.populate_tf_resource_alb(
        spec=alb_spec_with_query_string, ocm_map=mock_alb_setup
    )

    mocked_add_resources.assert_called_once()
    identifier, tf_resources = mocked_add_resources.call_args.args
    assert identifier == "a"

    # Find the listener rule resource that should contain our query-string condition
    listener_rules = [
        r for r in tf_resources if str(type(r).__name__) == "aws_lb_listener_rule"
    ]
    assert len(listener_rules) == 1

    listener_rule = listener_rules[0]
    conditions = listener_rule.condition
    assert len(conditions) == 1

    condition = conditions[0]
    assert "query_string" in condition
    expected_query_string = [
        {"key": "version", "value": "v1"},
        {"key": "env", "value": "prod"},
    ]
    assert condition["query_string"] == expected_query_string


def test_populate_tf_resource_alb_with_query_string_none_key_condition(
    mocker: MockerFixture,
    ts_for_alb: TerrascriptClient,
    alb_spec_with_query_string_none_key: ExternalResourceSpec,
    mock_alb_setup: MagicMock,
) -> None:
    mocked_add_resources = mocker.patch.object(ts_for_alb, "add_resources")
    mocker.patch.object(ts_for_alb, "_multiregion_account", return_value=True)

    ts_for_alb.populate_tf_resource_alb(
        spec=alb_spec_with_query_string_none_key, ocm_map=mock_alb_setup
    )

    mocked_add_resources.assert_called_once()
    identifier, tf_resources = mocked_add_resources.call_args.args
    assert identifier == "a"

    # Find the listener rule resource that should contain our query-string condition
    listener_rules = [
        r for r in tf_resources if str(type(r).__name__) == "aws_lb_listener_rule"
    ]
    assert len(listener_rules) == 1

    listener_rule = listener_rules[0]
    conditions = listener_rule.condition
    assert len(conditions) == 1

    condition = conditions[0]
    assert "query_string" in condition
    expected_query_string = [
        {"key": None, "value": "debug"},
        {"key": "version", "value": "v2"},
    ]
    assert condition["query_string"] == expected_query_string
